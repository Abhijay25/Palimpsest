"""Budgeted, cached OpenAI calls. Never log credentials or raw HTTP errors."""
import hashlib,json,os,time,re,math
from pathlib import Path
import requests
from contextlib import contextmanager
from core import ROOT,connect

MODEL='gpt-6-luna'
class APIError(RuntimeError): pass
class BudgetError(RuntimeError): pass

def budget_limit():
    # The user explicitly removed the original $10 pilot cap on 2026-11-14.
    raw=os.getenv('NEOWIKI_API_TOTAL_LIMIT_USD','').strip()
    if not raw:return None
    value=float(raw)
    if not math.isfinite(value) or value<0:raise BudgetError('Invalid configured API spending limit.')
    return value

def within_budget(spent,reservation,limit=None):
    limit=budget_limit() if limit is None else limit
    return math.isfinite(spent) and math.isfinite(reservation) and spent>=0 and reservation>=0 and (limit is None or spent+reservation<=limit)

def key():
    values={}
    for name in ('.env','.env.local'):
        p=ROOT/name
        if p.exists():
            for line in p.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k,v=line.split('=',1); values[k.strip().removeprefix('export ')]=v.strip().strip('\"\'')
    value=os.getenv('OPENAI_API_KEY') or values.get('OPENAI_API_KEY') or values.get('OPEN_API_KEY')
    if not value: raise APIError('No API key configured.')
    return value

def init():
    with connect() as db,db.cursor() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS api_call (
          id CHAR(64) PRIMARY KEY, stage VARCHAR(40), status VARCHAR(20),
          reserved DECIMAL(12,8), cost DECIMAL(12,8), input_tokens INT DEFAULT 0,
          output_tokens INT DEFAULT 0, latency_ms INT DEFAULT 0, result LONGTEXT,
          created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

@contextmanager
def provider_slot(stage):
    """Database-backed limits apply across the preparation and naming processes."""
    held=[]
    with connect() as db,db.cursor() as cursor:
        try:
            pools=[('neowiki_title_worker_',2)] if stage=='question_titles' else []
            pools.append(('neowiki_provider_worker_',6))
            for prefix,capacity in pools:
                deadline=time.monotonic()+180
                while True:
                    acquired=False
                    for index in range(capacity):
                        name=prefix+str(index)
                        cursor.execute('SELECT GET_LOCK(%s,0) locked',(name,))
                        if cursor.fetchone()['locked']==1:
                            held.append(name);acquired=True;break
                    if acquired:break
                    if time.monotonic()>deadline:raise APIError('Preparation workers are busy; request reservation retained.')
                    time.sleep(.15)
            yield
        finally:
            for name in reversed(held):cursor.execute('SELECT RELEASE_LOCK(%s)',(name,))


def call(endpoint,payload,stage):
    if endpoint!='decisions' and not (endpoint=='responses' and stage=='question_titles'):
        raise APIError('Text generation is enabled only for cached question naming.')
    body=json.dumps(payload,ensure_ascii=False)
    namespace=os.environ.get('NEOWIKI_ON_DEMAND_NAMESPACE','')
    identity=hashlib.sha256((namespace+endpoint+body).encode()).hexdigest()
    # UTF-8 byte count bounds token count conservatively. Use long-context rates,
    # plus a margin for server serialization; never credit discounts in the ceiling.
    reservation=(len(body.encode())+4096)*.25/1e6+(payload.get('max_output_tokens',0)*1/1e6)
    with connect() as db,db.cursor() as c:
        c.execute("SELECT GET_LOCK('language_gap_api_budget',10) AS locked")
        if c.fetchone()['locked']!=1: raise BudgetError('Budget ledger busy.')
        try:
            c.execute('SELECT * FROM api_call WHERE id=%s',(identity,)); old=c.fetchone()
            if old:
                if old['status']=='done': return json.loads(old['result'])
                raise APIError('An earlier request failed or is unresolved; inspect ledger before retrying.')
            c.execute('SELECT COALESCE(SUM(CASE WHEN status=\'done\' THEN cost ELSE reserved END),0) AS total FROM api_call')
            if not within_budget(float(c.fetchone()['total']),reservation): raise BudgetError('Configured API ceiling reached.')
            c.execute("INSERT INTO api_call(id,stage,status,reserved) VALUES (%s,%s,'reserved',%s)",(identity,stage,reservation))
        finally: c.execute("SELECT RELEASE_LOCK('language_gap_api_budget')")
    started=time.monotonic()
    try:
        with provider_slot(stage):
            response=requests.post('https://api.openai.com/v1/'+endpoint,
              headers={'Authorization':'Bearer '+key(),'Content-Type':'application/json'},
              data=body.encode(),timeout=(15,120))
        if not response.ok:
            try: detail=response.json().get('error',{}).get('message','Request rejected.')
            except ValueError: detail='Request rejected.'
            detail=re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',detail).replace(key(),'[redacted]')
            raise APIError(f'{endpoint}: HTTP {response.status_code}. {detail[:700]}')
        result=response.json()
        usage=result.get('usage',{}); incoming=usage.get('input_tokens',0); outgoing=usage.get('output_tokens',0)
        # Conservatively account at long-context input/output rates. This is a
        # metered upper estimate, not a statement of the eventual invoice.
        cost=incoming*.25/1e6+outgoing*1/1e6 if 'input_tokens' in usage and 'output_tokens' in usage else reservation
        if cost>reservation: raise BudgetError('Usage exceeded reservation; stop and audit pricing.')
        with connect() as db,db.cursor() as c:
            c.execute("UPDATE api_call SET status='done',cost=%s,input_tokens=%s,output_tokens=%s,latency_ms=%s,result=%s WHERE id=%s",
                (cost,incoming,outgoing,int((time.monotonic()-started)*1000),json.dumps(result),identity))
        return result
    except Exception as error:
        with connect() as db,db.cursor() as c:
            c.execute("UPDATE api_call SET status='failed' WHERE id=%s",(identity,))
        if isinstance(error,(APIError,BudgetError)): raise
        raise APIError('API request failed or timed out. Reservation retained; no automatic retry.') from None

def structured(instructions,evidence,schema,stage):
    result=call('responses',{'model':MODEL,'instructions':instructions,
      'input':json.dumps(evidence,ensure_ascii=False),'max_output_tokens':8192,
      'reasoning':{'effort':'low'},
      'text':{'format':{'type':'json_schema','name':stage,'strict':True,'schema':schema}}},stage)
    texts=[p['text'] for item in result.get('output',[]) for p in item.get('content',[]) if p.get('type')=='output_text']
    if result.get('status')!='completed' or not texts: raise APIError('Generation incomplete or refused.')
    return json.loads(''.join(texts))

def decisions(evidence,questions,allow_refusals=False):
    result=call('decisions',{'model':MODEL,'input':json.dumps(evidence,ensure_ascii=False),'questions':questions},'decisions')
    if not allow_refusals and any(a.get('type')=='refusal' for a in result['answers']): raise APIError('Decision refused.')
    return {a['name']:a for a in result['answers']}

def object_schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}

if __name__=='__main__':
    init()
    r=decisions({'a':'The law was adopted in 1999.','b':'The law took effect in 2000.'},[
      {'type':'predicate','name':'contradiction','instructions':'Do these statements necessarily contradict? Different legislative milestones can have different dates.'}])
    print(json.dumps(r))

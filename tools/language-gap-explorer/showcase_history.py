"""Real, revision-pinned historical replay. Reads never fetch or spend."""
import argparse,difflib,hashlib,json,re,time,threading
_api_lock=threading.Lock()
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import requests
from core import ROOT,connect,vector_bytes
from pipeline import articles,digest
TOPIC='Q2606233'
CACHE=ROOT/'data'/'showcase-history'

class Prose(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.out=[];self.skip=0;self.stack=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=a.get('class','').split()
        blocked=tag in ('script','style','table','sup') or any(c in classes for c in ('mw-editsection','reflist','references','navbox','hatnote','metadata','toc'))
        self.stack.append((tag,self.skip)) if tag not in ('br','img','hr','meta','link','wbr','input') else None
        if blocked:self.skip+=1
        if self.skip:return
        if tag in ('p','div','li','ul','ol'):self.out.append('\n\n')
        if re.fullmatch('h[1-6]',tag):self.out.append('\n\n'+'#'*int(tag[1])+' ')
        if tag=='br':self.out.append('\n')
    def handle_endtag(self,tag):
        if not self.skip and tag in ('p','div','li','h1','h2','h3','h4','h5','h6'):self.out.append('\n\n')
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.skip=self.stack[i][1];self.stack=self.stack[:i];break
    def handle_data(self,data):
        if not self.skip:self.out.append(data)
    def text(self):return '\n\n'.join(re.sub(r'\s+',' ',p).strip() for p in ''.join(self.out).split('\n\n') if p.strip())

def api(lang,params):
    CACHE.mkdir(parents=True,exist_ok=True);p=CACHE/(digest([lang,params])+'.json')
    if p.exists():return json.loads(p.read_text(encoding='utf-8'))
    with _api_lock:
        for attempt in range(5):
            time.sleep(1)
            r=requests.get(f'https://{lang}.wikipedia.org/w/api.php',params=dict(format='json',formatversion=2,**params),headers={'User-Agent':'LanguageGapExplorer/0.3 (read-only historical research prototype)'},timeout=(10,45))
            if r.status_code not in (429,503):break
            time.sleep(min(30,5*(attempt+1)))
        r.raise_for_status();data=r.json()
    if 'error' in data:raise ValueError('Wikipedia: '+data['error'].get('info','Request failed'))
    tmp=p.with_suffix('.part');tmp.write_text(json.dumps(data),encoding='utf-8');tmp.replace(p);return data

def revision(lang,rev):
    data=api(lang,dict(action='parse',oldid=int(rev),prop='text'));parser=Prose();parser.feed(data['parse']['text']);return parser.text()

def init():
    with connect() as db,db.cursor() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS showcase_event(id CHAR(64) PRIMARY KEY,topic VARCHAR(24),lang CHAR(2),before_rev BIGINT,after_rev BIGINT,stamp VARCHAR(30),summary TEXT,kind VARCHAR(30),payload LONGTEXT,status VARCHAR(30) DEFAULT 'pending',note TEXT,assessment LONGTEXT) CHARACTER SET utf8mb4''')
        c.execute('''CREATE TABLE IF NOT EXISTS showcase_passage(id CHAR(64) PRIMARY KEY,lang CHAR(2),rev_id BIGINT,ordinal INT,heading TEXT,text TEXT,embedding VECTOR(384),KEY revision(lang,rev_id)) CHARACTER SET utf8mb4''')
        c.execute('''CREATE TABLE IF NOT EXISTS showcase_review(id INT AUTO_INCREMENT PRIMARY KEY,event_id CHAR(64),action VARCHAR(30),note TEXT,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP) CHARACTER SET utf8mb4''')
        c.execute('''CREATE TABLE IF NOT EXISTS showcase_issue_review(id INT AUTO_INCREMENT PRIMARY KEY,event_id CHAR(64),lang CHAR(2),action VARCHAR(30),note TEXT,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,KEY edition(event_id,lang)) CHARACTER SET utf8mb4''')
        c.execute('''CREATE TABLE IF NOT EXISTS showcase_state(id INT PRIMARY KEY,status VARCHAR(30),message TEXT,updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP) CHARACTER SET utf8mb4''')

def state(status,message):
    with connect() as db,db.cursor() as c:c.execute('REPLACE INTO showcase_state(id,status,message) VALUES (1,%s,%s)',(status,message))

def events():
    with connect() as db,db.cursor() as c:
        c.execute('SELECT * FROM showcase_event ORDER BY stamp DESC,after_rev DESC');rows=list(c.fetchall())
        c.execute('SELECT * FROM showcase_state WHERE id=1');status=c.fetchone()
    for row in rows:row['data']=json.loads(row['payload']);row['check']=json.loads(row['assessment']) if row['assessment'] else None
    return rows,status

def index_revision(lang,rev,text,model):
    from pipeline import split_article
    with connect() as db,db.cursor() as c:
        c.execute('SELECT COUNT(*) n FROM showcase_passage WHERE lang=%s AND rev_id=%s',(lang,rev))
        if c.fetchone()['n']:return
    parts=list(split_article(dict(lang=lang,rev_id=rev,text=text),model.model.tokenizer))
    vv=list(model.embed(['query: '+p['text'] for p in parts],batch_size=8)) if parts else []
    with connect() as db,db.cursor() as c:
        for p,v in zip(parts,vv):c.execute('INSERT IGNORE INTO showcase_passage VALUES (%s,%s,%s,%s,%s,%s,%s)',(digest([lang,rev,p['ordinal']]),lang,rev,p['ordinal'],p['heading'],p['text'],vector_bytes(v)))

def changes(before,after):
    aa=before.split('\n\n');bb=after.split('\n\n');result=[]
    for tag,a,b,x,y in difflib.SequenceMatcher(None,aa,bb,autojunk=False).get_opcodes():
        if tag=='equal':continue
        # Keep every changed paragraph, pairing within each changed block.
        for i in range(max(b-a,y-x)):
            old=aa[a+i] if a+i<b else '';new=bb[x+i] if x+i<y else ''
            if (not new and old in bb) or (not old and new in aa):continue
            if (old or new).startswith('#') and max(len(old),len(new))<180:continue
            result.append(dict(before=old,after=new))
    return result

def asof_time(event_time,snapshot_time):
    return min(event_time,snapshot_time)

def prepare(limit=20):
    from prepare import embedding_model
    init();state('running','Importing real historical revisions.');model=embedding_model();aa=articles(TOPIC)
    try:
        cutoffs={}
        for lang,a in aa.items():
            p=api(lang,dict(action='query',prop='revisions',revids=a['rev_id'],rvprop='ids|timestamp'))['query']['pages'][0]
            cutoffs[lang]=p['revisions'][0]['timestamp']
        history=[]
        for lang,a in aa.items():
            pp=api(lang,dict(action='query',prop='revisions',pageids=a['page_id'],rvstartid=a['rev_id'],rvlimit=limit,rvprop='ids|timestamp|comment'))['query']['pages'][0]
            history.extend((lang,v) for v in pp.get('revisions',[]) if v.get('parentid'))
        pairs={(l,int(v[k])) for l,v in history for k in ('revid','parentid')}
        with ThreadPoolExecutor(max_workers=3) as pool:rendered=dict(zip(sorted(pairs),pool.map(lambda p:revision(*p),sorted(pairs))))
        for count,(lang,v) in enumerate(sorted(history,key=lambda p:p[1]['timestamp'])):
            identity=digest([lang,v['parentid'],v['revid']])
            with connect() as db,db.cursor() as c:
                c.execute('SELECT id FROM showcase_event WHERE id=%s',(identity,))
                if c.fetchone():continue
            before=rendered[(lang,v['parentid'])];after=rendered[(lang,v['revid'])];diffs=changes(before,after)
            targets=[]
            for target,a in aa.items():
                if not diffs:break
                if target==lang:continue
                at=asof_time(v['timestamp'],cutoffs[target])
                pages=api(target,dict(action='query',prop='revisions',pageids=a['page_id'],rvstart=at,rvdir='older',rvlimit=1,rvprop='ids|timestamp'))['query']['pages']
                revisions=pages[0].get('revisions',[])
                if not revisions:continue
                r=revisions[0];text=revision(target,r['revid']);index_revision(target,r['revid'],text,model);targets.append((target,r))
            for d in diffs:
                quote=d['after'] or d['before'];vec=vector_bytes(next(model.embed(['query: '+quote])));d['counterparts']=[]
                with connect() as db,db.cursor() as c:
                    for target,r in targets:
                        c.execute('''SELECT text,heading,1-VEC_DISTANCE_COSINE(embedding,%s) similarity FROM showcase_passage WHERE lang=%s AND rev_id=%s ORDER BY VEC_DISTANCE_COSINE(embedding,%s)+0 LIMIT 3''',(vec,target,r['revid'],vec))
                        candidates=list(c.fetchall())
                        if candidates:d['counterparts'].append(dict(lang=target,rev_id=r['revid'],stamp=r['timestamp'],**candidates[0],alternatives=candidates[1:]))
            with connect() as db,db.cursor() as c:c.execute('INSERT IGNORE INTO showcase_event(id,topic,lang,before_rev,after_rev,stamp,summary,kind,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(identity,TOPIC,lang,v['parentid'],v['revid'],v['timestamp'],v.get('comment',''),'prose' if diffs else 'formatting',json.dumps(dict(changes=diffs))))
            print('Historical edit',count+1,'/',len(history),lang,v['revid'],len(diffs),'changed paragraphs',flush=True)
            state('running',f'Imported {count+1} / {len(history)} historical edits.')
        remove_moved_alerts()
        state('done',f'Replayed {len(history)} real historical edits, at most {limit} per language.');return events()
    except Exception as e:state('failed','History import incomplete: '+type(e).__name__+'. Rerun preparation to resume.');raise

def review(identity,action,note):
    if action not in ('needs_update','already_covered','no_update') or not note.strip():raise ValueError('Choose an outcome and add a reviewer note.')
    with connect() as db,db.cursor() as c:
        db.begin()
        try:
            c.execute('SELECT id FROM showcase_event WHERE id=%s FOR UPDATE',(identity,))
            if not c.fetchone():raise ValueError('Unknown historical edit.')
            c.execute('UPDATE showcase_event SET status=%s,note=%s WHERE id=%s',(action,note[:4000],identity));c.execute('INSERT INTO showcase_review(event_id,action,note) VALUES (%s,%s,%s)',(identity,action,note[:4000]));db.commit()
        except Exception:db.rollback();raise


def remove_moved_alerts():
    # Refresh deterministic presentation after extraction fixes; preserve reviews.
    rows,_=events()
    for row in rows:
        before=revision(row['lang'],row['before_rev']);after=revision(row['lang'],row['after_rev'])
        valid={(d['before'],d['after']) for d in changes(before,after)}
        kept=[d for d in row['data']['changes'] if (d['before'],d['after']) in valid]
        if len(kept)==len(row['data']['changes']):continue
        with connect() as db,db.cursor() as c:c.execute('UPDATE showcase_event SET payload=%s,kind=%s WHERE id=%s',(json.dumps({'changes':kept}),'prose' if kept else 'formatting',row['id']))


def edition_reviews(lang):
    with connect() as db,db.cursor() as c:
        c.execute('SELECT * FROM showcase_issue_review WHERE lang=%s ORDER BY id DESC',(lang,));rows=c.fetchall()
    latest={}
    for row in rows:latest.setdefault(row['event_id'],row)
    return latest

def review_issue(identity,lang,action,note):
    if lang not in ('en','fi','sv') or action not in ('needs_update','already_covered','no_update') or not note.strip():raise ValueError('Choose an outcome and add a reviewer note.')
    with connect() as db,db.cursor() as c:
        c.execute('SELECT id FROM showcase_event WHERE id=%s',(identity,))
        if not c.fetchone():raise ValueError('Unknown historical edit.')
        c.execute('INSERT INTO showcase_issue_review(event_id,lang,action,note) VALUES (%s,%s,%s,%s)',(identity,lang,action,note[:4000]))

"""Explicit localhost fixture UI, using the real durable queue and no providers.

Run manually for bounded desktop/mobile browser verification. This server never
imports an inference adapter. Its source texts and outcomes are synthetic.
"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlsplit
import on_demand_jobs as jobs

ROOT=Path(__file__).resolve().parent.parent.parent
TOKEN='offline-fixture-csrf'
SCOPE='offline-fixture-en'
TOPIC='Q134949'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,value,mime='application/json',status=200):
        data=value.encode() if isinstance(value,str) else json.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/jobs.js':return self.respond((ROOT/'infra/wiki/extensions/PalimpsestIssues/resources/jobs.js').read_text(encoding='utf-8'),'text/javascript')
        if path=='/issues.css':return self.respond((ROOT/'infra/wiki/extensions/PalimpsestIssues/resources/issues.css').read_text(encoding='utf-8'),'text/css')
        if path!='/':return self.respond({},status=404)
        self.respond('''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline native request fixture</title><link rel="stylesheet" href="/issues.css"><style>body{font:16px Arial,sans-serif;color:#202122;background:white;margin:24px auto;max-width:1000px;padding:0 16px}h1,h2,h3{font-family:Georgia,serif}a{color:#3366cc}button{cursor:pointer}button:disabled{cursor:default}#fixture-notice{padding:12px;background:#f8f9fa;border:1px solid #a2a9b1}code{font-size:13px}</style><h1>Winter War · Issues</h1><p id="fixture-notice">OFFLINE SYNTHETIC FIXTURE. Real durable queue, synthetic sources/results, no provider calls or production database writes.</p><label>Source revision<select id="flags-revision"><option value="123">123 · synthetic 2020-01-01</option></select></label><section id="native-jobs"></section><script src="/jobs.js"></script><script>
async function call(op,selection={},extra={}){const response=await fetch('/fixture/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op,selection,extra,token:'offline-fixture-csrf'})});const data=await response.json();if(!response.ok)throw Error(data.error);return data;}
PalimpsestJobs.mount({host:document.getElementById('native-jobs'),call,url:()=>'/#synthetic-stored-issues',edition:'en',canScan:true,revision:()=>document.getElementById('flags-revision').value});
</script>''','text/html; charset=utf-8')
    def do_POST(self):
        if self.path!='/fixture/request':return self.respond({},status=404)
        data=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length',0)),65536)))
        if data.get('token')!=TOKEN:return self.respond({'error':'Fixture CSRF required'},status=403)
        try:
            op=data['op'];selection=data.get('selection',{})
            if op=='jobpolicy':
                from on_demand_bridge import describe
                value=describe(TOPIC)
            elif op=='jobs':value={'jobs':jobs.recent(SCOPE,TOPIC)}
            elif op=='jobplan':
                kind=data['extra']['mode'];p=jobs.policy();sources=[]
                for lang in (selection.get('languages',['en']) if kind=='language' else ['en']):
                    text='Synthetic offline source '+lang
                    sources.append(dict(lang=lang,title='Winter War',page_id=12,revision_id=123,parent_id=122,timestamp='2020-01-01T00:00:00Z',wikitext=text,sha256=hashlib.sha256(text.encode()).hexdigest()))
                value={'plan':jobs.save_plan(SCOPE,dict(version='offline-fixture',kind=kind,topic=TOPIC,engine=p['engines'][kind]['configuration'],authorization=jobs.digest(p),implementation='offline-fixture',policy_version='OFFLINE FIXTURE'),sources)}
            elif op=='enqueue':
                job=jobs.enqueue(selection['plan'],SCOPE,TOPIC,1,selection.get('previous'));value={'job':job}
                if job['status']=='queued':threading.Thread(target=complete,args=(job['id'],),daemon=True).start()
            else:raise ValueError('Unknown fixture operation')
            self.respond(value)
        except Exception as error:self.respond({'error':str(error)},status=400)


def complete(identity):
    time.sleep(1);jobs.update(identity,'running',dict(stage='synthetic fixture processing',provider_calls=0))
    time.sleep(3);jobs.update(identity,'completed',result=dict(findings=0,partial=False,provider_usage={'calls':0},fixture=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8077);args=parser.parse_args()
    directory=tempfile.TemporaryDirectory(prefix='neowiki-offline-browser-')
    folder=Path(directory.name);os.environ['NEOWIKI_ON_DEMAND_ROOT']=str(folder/'queue');os.environ['NEOWIKI_ON_DEMAND_POLICY']=str(folder/'policy.json')
    detector=dict(provider='gemini',model='OFFLINE-FIXTURE-NO-PROVIDER',reviewer_model='offline',triage_model='offline',prompt_version='offline',policy_version='offline',max_output_tokens=1)
    policy=dict(version=1,policy_version='offline',enabled=True,authorization='OFFLINE SYNTHETIC FIXTURE — NO INFERENCE',engines={k:dict(configuration=detector if k!='language' else dict(provider='openai',model='OFFLINE-FIXTURE-NO-PROVIDER',prompt_version='offline',policy_version='offline'),enabled=True,topics=[TOPIC],authorization='OFFLINE FIXTURE',max_provider_calls=1,allow_rescan=True) for k in ('page','revision','language')})
    (folder/'policy.json').write_text(json.dumps(policy),encoding='utf-8');jobs.init()
    print(f'Offline UI fixture http://127.0.0.1:{args.port}',flush=True)
    try:ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
    finally:directory.cleanup()


if __name__=='__main__':main()

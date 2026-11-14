"""Prepare the one-topic real-data showcase and export reproducible results."""
import argparse,json,time
from core import connect,ROOT
from pipeline import init,enqueue,work,latest,VERSION
from showcase_history import init as history_init,prepare,events,TOPIC

def run_review():
    identity=enqueue(TOPIC)
    with connect() as db,db.cursor() as c:c.execute('SELECT * FROM review_run WHERE id=%s',(identity,));run=c.fetchone()
    if run['status']!='done':work(run)
    return latest(TOPIC)

def export(start):
    run,findings=latest(TOPIC);rows,status=events()
    with connect() as db,db.cursor() as c:c.execute("SELECT COUNT(*) requests,SUM(CASE WHEN status='done' THEN cost ELSE reserved END) used_or_reserved FROM api_call");usage=c.fetchone()
    report=dict(topic=TOPIC,snapshot=run['snapshot'] if run else None,settings=dict(model='intfloat/multilingual-e5-small',dimensions=384,chunk_target=280,chunk_cap=400,neighbours=3,search='exact cosine within topic and target revision'),run=run,findings=findings,history_status=status,history_edits=len(rows),history_prose_edits=sum(r['kind']=='prose' for r in rows),elapsed_seconds=round(time.monotonic()-start,2),global_api_ledger=usage,accuracy='Not established; human review required.')
    folder=ROOT/'reports';folder.mkdir(exist_ok=True);(folder/'tornedalians-showcase.json').write_text(json.dumps(report,default=str,indent=2),encoding='utf-8');print('Exported reports/tornedalians-showcase.json',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--history-limit',type=int,default=20);p.add_argument('--run-review',action='store_true');a=p.parse_args()
    if not 1<=a.history_limit<=20:p.error('History limit must be between 1 and 20.')
    start=time.monotonic();init();history_init()
    if a.prepare:prepare(a.history_limit)
    if a.run_review:run_review()
    export(start)

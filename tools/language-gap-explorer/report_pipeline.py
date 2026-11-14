import json
from core import ROOT,connect
from pipeline import VERSION

def report():
    with connect() as db,db.cursor() as c:
        c.execute('SELECT topic,status,progress,total,error,created,updated FROM review_run WHERE version=%s ORDER BY created',(VERSION,)); runs=c.fetchall()
        c.execute('SELECT stage,status,COUNT(*) AS calls,SUM(cost) AS estimated_cost,SUM(reserved) AS reserved,SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,AVG(latency_ms) AS mean_latency_ms FROM api_call GROUP BY stage,status'); usage=c.fetchall()
        c.execute("SELECT payload,claims,judgments,findings FROM review_group WHERE status='done' LIMIT 20"); review=c.fetchall()
        c.execute('SELECT report FROM review_evaluation WHERE id=1'); evaluation=c.fetchone()
    completed=sum(r['progress'] for r in runs)
    cost=sum(float(r['estimated_cost'] or 0) for r in usage)
    data={'runs':runs,'usage':usage,'evaluation':json.loads(evaluation['report']) if evaluation else None,
      'completed_groups':completed,'conservative_cost_per_completed_group':cost/completed if completed else None,
      'full_corpus_estimate':'Requires a completed representative pilot; no reliable full-corpus estimate yet.',
      'human_review_groups_exported':len(review),'real_world_accuracy':'Not established; bilingual human review required.'}
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports'/'pilot-progress.json').write_text(json.dumps(data,default=str,indent=2),encoding='utf-8')
    (ROOT/'reports'/'bilingual-review.json').write_text(json.dumps(review,default=str,indent=2),encoding='utf-8')
    print(json.dumps(data,default=str,indent=2))

if __name__=='__main__': report()

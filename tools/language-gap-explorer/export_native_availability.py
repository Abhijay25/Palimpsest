"""Explicitly export verified native root availability; browsing never does this."""
import argparse
import hashlib
import json
from pathlib import Path
from core import connect
from on_demand_jobs import packed,now


def export(provenance_root,output):
    result=dict(version=1,created_at=now(),editions={})
    for lang in ('en','fi','sv'):
        bundle=json.loads((provenance_root/lang/(lang+'.json')).read_text(encoding='utf-8'))
        if bundle.get('schema_version')!=1 or bundle.get('language')!=lang or bundle.get('source_wiki')!=lang+'wiki' or hashlib.sha256(packed(bundle['payload']).encode()).hexdigest()!=bundle['sha256']:
            raise ValueError('Invalid native provenance; previous availability file is preserved.')
        pages={int(p['source_page_id']):p for p in bundle['payload']['pages'] if int(p.get('local_page_id') or 0)>0 and any(int(r.get('local_revision_id') or 0)>0 for r in p.get('revisions',[]))}
        if not pages:
            result['editions'][lang]={};continue
        with connect() as db,db.cursor() as c:
            c.execute('SELECT wikidata_id,page_id,title FROM article WHERE lang=%s AND page_id IN ('+','.join(['%s']*len(pages))+')',[lang,*pages])
            rows=list(c.fetchall())
        result['editions'][lang]={}
        for row in rows:
            page=pages[int(row['page_id'])]
            if page['title']!=row['title'] or not row['wikidata_id']:continue
            result['editions'][lang][row['wikidata_id']]=dict(title=page['title'],source_page_id=page['source_page_id'],local_page_id=page['local_page_id'],provenance_sha256=bundle['sha256'])
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.part');temporary.write_text(packed(result),encoding='utf-8');temporary.replace(output)
    return {lang:len(rows) for lang,rows in result['editions'].items()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--provenance-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(export(args.provenance_root,args.output)))

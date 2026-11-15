"""Explicit approved four-article demo population, separate from Winter War.

Preparation freezes sources only. Enqueue requires the matching private policy;
the ordinary durable worker executes it with the same retained reservations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import requests
from core import connect
import on_demand_jobs as jobs
from on_demand_bridge import fetch_source,implementation_identity,source_record

ANCHORS={
 'Q122100':{'en':1304070619,'fi':23388335,'sv':57639824},
 'Q211855':{'en':1307003624,'fi':23498098,'sv':57158733},
 'Q154940':{'en':1303461171,'fi':23340989,'sv':56730588},
 'Q202808':{'en':1287977631,'fi':23422349,'sv':57526430}}


def native_source(lang,rid,title,page_id):
    """Use an actual imported source/local map; never put a source ID in oldid."""
    folder=os.environ.get('NEOWIKI_NATIVE_PROVENANCE')
    apis=json.loads(os.environ.get('NEOWIKI_NATIVE_APIS','{}'))
    if not folder or not apis.get(lang):return None
    bundle=json.loads((Path(folder)/lang/(lang+'.json')).read_text(encoding='utf-8'))
    if bundle['sha256']!=hashlib.sha256(jobs.packed(bundle['payload']).encode()).hexdigest():raise ValueError('Native provenance checksum mismatch.')
    pages=[p for p in bundle['payload']['pages'] if p['title']==title and int(p['source_page_id'])==int(page_id)]
    if len(pages)!=1:return None
    rows=[r for r in pages[0]['revisions'] if int(r['source_revision_id'])==int(rid)]
    if len(rows)!=1:return None
    record=rows[0]
    response=requests.get(apis[lang],params=dict(action='query',prop='revisions',revids=record['local_revision_id'],rvprop='ids|timestamp|content',rvslots='main',format='json',formatversion=2),timeout=20)
    response.raise_for_status();value=response.json()['query']['pages'][0]['revisions'][0]
    slot=value['slots']['main'];text=slot.get('content',slot.get('*'))
    if int(value['revid'])!=int(record['local_revision_id']) or value['timestamp']!=record['timestamp'] or hashlib.sha256(text.encode()).hexdigest()!=record['sha256']:
        raise ValueError('Native content no longer matches the exact imported source.')
    return dict(lang=lang,title=title,page_id=page_id,revision_id=int(rid),parent_id=record.get('source_parent_id'),timestamp=record['timestamp'],wikitext=text,sha256=record['sha256'])


def prepare():
    p=jobs.policy()
    if p.get('allow_operator_batch') is not True:raise ValueError('An explicit operator batch authorization is required.')
    scopes=json.loads(os.environ['NEOWIKI_NATIVE_SCOPES'])
    with connect() as db,db.cursor() as c:
        c.execute('SELECT wikidata_id,lang,page_id,rev_id,title,date_modified FROM article WHERE wikidata_id IN (%s,%s,%s,%s) ORDER BY wikidata_id,lang',list(ANCHORS))
        rows=list(c.fetchall())
    if len(rows)!=12:raise ValueError('The twelve approved dataset editions are not all available.')
    output=dict(authorization_id=p['authorization_id'],implementation=implementation_identity(),created_at=jobs.now(),plans=[],errors=[])
    for row in rows:
        from on_demand_worker import disk
        disk()
        lang=row['lang'];topic=row['wikidata_id']
        if lang not in ANCHORS[topic] or int(row['rev_id'])!=ANCHORS[topic][lang]:raise ValueError('Dataset anchor differs from the approved source plan.')
        try:
            source=native_source(lang,row['rev_id'],row['title'],row['page_id']) or source_record(lang,row['rev_id'],row['title'],page_id=row['page_id'])
            if source['timestamp']!=row['date_modified']:raise ValueError('Source time differs from the dataset anchor.')
        except Exception as error:
            output['errors'].append(dict(topic=topic,lang=lang,stage='source',error=type(error).__name__));continue
        for kind in ('page','revision'):
            try:
                locked=dict(source)
                if kind=='revision':
                    if not source.get('parent_id'):raise ValueError('Exact parent is unavailable.')
                    parent=native_source(lang,source['parent_id'],row['title'],row['page_id']) or source_record(lang,source['parent_id'],row['title'])
                    locked.update(parent_wikitext=parent['wikitext'],parent_sha256=parent['sha256'])
                config=dict(version='native-on-demand-v1',kind=kind,topic=topic,engine=p['engines'][kind]['configuration'],
                    implementation=output['implementation'],authorization=jobs.digest(p),authorization_id=p['authorization_id'],policy_version=p['policy_version'])
                plan=jobs.save_plan(scopes[lang],config,[locked])
                output['plans'].append(dict(plan=plan['id'],scope=scopes[lang],topic=topic,lang=lang,kind=kind,revision=source['revision_id'],sha256=source['sha256']))
            except Exception as error:output['errors'].append(dict(topic=topic,lang=lang,stage=kind,error=type(error).__name__))
    target=jobs.root()/'demo-plan.json';temporary=target.with_suffix('.part');temporary.write_text(jobs.packed(output),encoding='utf-8');temporary.replace(target)
    print(jobs.packed(dict(prepared=len(output['plans']),unavailable=output['errors'],provider_calls=0,manifest=str(target))))


def enqueue():
    manifest=json.loads((jobs.root()/'demo-plan.json').read_text(encoding='utf-8'))
    if manifest['implementation']!=implementation_identity():raise ValueError('Prepared source code changed.')
    result=[]
    for plan in manifest['plans']:
        job=jobs.enqueue_operator(plan['plan'],plan['scope'],plan['topic'],manifest['authorization_id'])
        result.append(dict(id=job['id'],topic=job['topic'],kind=job['kind'],status=job['status']))
    print(jobs.packed(dict(jobs=result,unavailable=manifest['errors'])))


def status():
    with jobs.database() as db:
        counts=[dict(r) for r in db.execute('SELECT topic,kind,status,COUNT(*) jobs FROM job GROUP BY topic,kind,status')]
        calls=[dict(r) for r in db.execute('SELECT status,COUNT(*) calls FROM attempt GROUP BY status')]
        findings=[dict(r) for r in db.execute("SELECT topic,kind,SUM(json_extract(result,'$.findings')) findings FROM job WHERE status IN ('completed','partial') GROUP BY topic,kind")]
    print(jobs.packed(dict(jobs=counts,provider_calls=calls,findings=findings)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','enqueue','status'));args=parser.parse_args()
    {'prepare':prepare,'enqueue':enqueue,'status':status}[args.command]()

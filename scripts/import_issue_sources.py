"""Explicit, bounded import of exact issue-source revisions into an owned wiki.

Shares the existing XML exporter, source normalization and source/local content
reconciliation. This is an evidence-scoped import, NEVER a complete-history
claim or a fabricated S-dataset manifest. No inference runs here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.palimpsest_data.history import fetch_json,revision_record,ensure_free_space
from scripts.palimpsest_data.importer import fetch_local_page,map_revisions
from scripts.palimpsest_data.io import atomic_json,canonical_json,sha256_bytes
from scripts.palimpsest_data.xml_export import mediawiki_xml,NS
from scripts.palimpsest_data.support import discover_support,source_support_resolver,title_key


def cached_support_resolver(language, progress, directory, api=fetch_json, retry_titles=()):
    """Explicit current-at-import dependency mode; article revisions stay exact.

    MediaWiki supports batch current revisions, but historical cutoff queries
    must be single-page. Never batch rvstart/rvlimit or claim current templates
    were the transclusions at the historical article date.
    """
    retry_keys={title_key(t) for t in retry_titles};attempted=set()
    def key(title,cutoff):return hashlib.sha256((cutoff+'|'+title_key(title)).encode()).hexdigest()
    def read(title,cutoff):
        path=directory/(key(title,cutoff)+'.json')
        if not path.exists():
            legacy=directory/(hashlib.sha256((cutoff+'|'+title.replace('_',' ').casefold()).encode()).hexdigest()+'.json')
            if legacy.exists():
                old=json.loads(legacy.read_text(encoding='utf-8'));record=old.get('record')
                if record and title_key(record['title'])==title_key(title):path=legacy
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        record=value.get('record') if value else None
        if value and record is None and title_key(title) in retry_keys-attempted:return None
        if record and hashlib.sha256(record['content'].encode()).hexdigest()!=record.get('computed_sha256'):
            raise ValueError('Template source cache integrity mismatch.')
        return value
    def resolve(title,cutoff):
        cached=read(title,cutoff)
        if cached is not None:return cached.get('record')
        pending=json.loads(progress.read_text(encoding='utf-8')).get('pending',[]) if progress.exists() else []
        names=[]
        for name in [title,*pending]:
            if title_key(name) not in {title_key(n) for n in names} and read(name,cutoff) is None:names.append(name)
            if len(names)>=40:break
        params=dict(action='query',format='json',formatversion=2,prop='info|revisions',titles='|'.join(names),
            rvprop='ids|timestamp|user|comment|flags|content|sha1|contentmodel|contentformat',rvslots='main')
        time.sleep(1)
        data=api('https://'+language+'.wikipedia.org/w/api.php?'+urlencode(params),retries=2)
        normalized={title_key(r['from']):r['to'] for r in data.get('query',{}).get('normalized',[])}
        pages={title_key(p['title']):p for p in data.get('query',{}).get('pages',[])}
        for name in names:
            canonical=normalized.get(title_key(name),name)
            page=pages.get(title_key(canonical));record=None
            if page and page.get('revisions'):
                raw=page['revisions'][0]
                article=dict(language=language,source_wiki=language+'wiki',source_page_id=page['pageid'],anchor_revision_id=raw['revid'])
                record=dict(revision_record(raw,article),title=page['title'])
            attempted.add(title_key(name))
            atomic_json(directory/(key(name,cutoff)+'.json'),dict(record=record))
        value=read(title,cutoff)
        return value.get('record') if value else None
    return resolve


def source_namespaces(language, names, directory, config, api=fetch_json):
    """Configure only explicitly requested non-core namespaces from source metadata."""
    path=directory/'siteinfo.json'
    if path.exists():data=json.loads(path.read_text(encoding='utf-8'))
    else:
        data=api('https://'+language+'.wikipedia.org/w/api.php?'+urlencode(dict(action='query',format='json',formatversion=2,meta='siteinfo',siprop='namespaces|namespacealiases')),retries=2)
        atomic_json(path,data)
    namespaces=data['query']['namespaces'];aliases=data['query'].get('namespacealiases',[])
    selected={}
    for name in names:
        matches=[int(key) for key,value in namespaces.items() if name.casefold() in {str(value.get('name','')).casefold(),str(value.get('canonical','')).casefold()}]
        matches.extend(int(a['id']) for a in aliases if name.casefold()==a.get('alias','').casefold())
        matches=set(matches)
        if len(matches)!=1:raise ValueError('Source namespace does not resolve uniquely: '+name)
        nsid=matches.pop()
        if nsid<100 or nsid in (828,829) or nsid>=10000:raise ValueError('Only additional source namespaces may be configured.')
        for number in [nsid,nsid+1] if nsid%2==0 else [nsid]:
            value=namespaces.get(str(number))
            if value:selected[number]=dict(id=number,name=value['name'].replace(' ','_'))
    records=[selected[k] for k in sorted(selected)]
    atomic_json(config,dict(source_wiki=language+'wiki',records=records,sha256=sha256_bytes(canonical_json(records))))
    return records


def exact_records(article, revisions, directory):
    records=[];missing=[]
    for rid in revisions:
        path=directory/(str(rid)+'.json')
        if path.exists():
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['source_revision_id']!=rid or row['source_page_id']!=article['source_page_id']:
                raise ValueError('Source cache identity mismatch.')
            if hashlib.sha256(row['content'].encode()).hexdigest()!=row['computed_sha256']:
                raise ValueError('Source cache integrity mismatch.')
            records.append(row)
        else:missing.append(rid)
    for start in range(0,len(missing),20):
        batch=missing[start:start+20]
        params=dict(action='query',format='json',formatversion=2,prop='revisions',revids='|'.join(map(str,batch)),
            rvprop='ids|timestamp|user|comment|flags|content|sha1|contentmodel|contentformat',rvslots='main')
        data=fetch_json('https://'+article['language']+'.wikipedia.org/w/api.php?'+urlencode(params),retries=2)
        acquired=[]
        for page in data.get('query',{}).get('pages',[]):
            if page.get('pageid')!=article['source_page_id'] or page.get('title')!=article['title']:
                raise ValueError('Exact revisions belong to a different source page/title.')
            for raw in page.get('revisions',[]):
                row=revision_record(raw,article)
                if row.get('content') is None:raise ValueError('Exact source text is unavailable; no substitute was imported.')
                atomic_json(directory/(str(row['source_revision_id'])+'.json'),row)
                acquired.append(row)
        if {r['source_revision_id'] for r in acquired}!=set(batch):raise ValueError('Some exact source revisions are unavailable.')
        records.extend(acquired)
    return sorted(records,key=lambda r:(r['timestamp'],r['source_revision_id']))


def run(args):
    # Only the explicit research-source lookup needs the research environment.
    # Importing this helper must not shadow another suite's test_pipeline module.
    research_path = str(ROOT/'tools/language-gap-explorer')
    added_path = research_path not in sys.path
    if added_path:
        sys.path.insert(0, research_path)
    try:
        from core import connect
    finally:
        if added_path:
            sys.path.remove(research_path)
    root=args.data_root.resolve();runtime=json.loads((root/'runtime.json').read_text(encoding='utf-8'))
    if runtime['project']!=args.project or Path(runtime['data_root']).resolve()!=root or not all(runtime['initialized'].values()):
        raise ValueError('The initialized runtime does not match this explicitly selected project/root.')
    ensure_free_space(root,2*1024**3)
    with connect() as db,db.cursor() as c:
        c.execute('SELECT page_id,title FROM article WHERE wikidata_id=%s AND lang=%s',(args.topic,args.language))
        rows=c.fetchall()
    if len(rows)!=1:raise ValueError('No unique source article for this topic/edition.')
    article=dict(language=args.language,source_wiki=args.language+'wiki',source_page_id=rows[0]['page_id'],
        title=rows[0]['title'],anchor_revision_id=max(args.revision))
    directory=root/'issue-sources'/args.language
    records=exact_records(article,sorted(set(args.revision)),directory)
    namespaces=source_namespaces(args.language,args.namespace,directory,root/'config'/args.language/'source-namespaces.json') if args.namespace else []
    anchor=records[-1]
    progress=root/'issue-support'/args.language/(str(article['source_page_id'])+('.current' if args.support_current else '')+'.progress.json')
    cutoff=(json.loads(progress.read_text(encoding='utf-8'))['cutoff'] if progress.exists() else __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat().replace('+00:00','Z')) if args.support_current else anchor['timestamp']
    seeds=list(args.include_dependency)
    if args.include_native_missing:
        parsed=fetch_json(runtime['languages'][args.language]['api_url']+'?'+urlencode(dict(action='parse',page=article['title'],prop='templates',format='json',formatversion=2)),retries=1)
        seeds.extend(t['title'] for t in parsed.get('parse',{}).get('templates',[]) if not t.get('exists'))
    resolver=cached_support_resolver(args.language,progress,root/'issue-support-current-cache'/args.language,retry_titles=seeds) if args.support_current else source_support_resolver(args.language,interval=1)
    if seeds:
        state=json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else dict(schema_version=1,root_title=article['title'],cutoff=cutoff,pending=[],visited=[],supporting=[],unresolved=[],edges={})
        seed_keys={title_key(s) for s in seeds};known={title_key(s['title']) for s in state['supporting']}
        retry=[r for r in state.get('unresolved',[]) if title_key(r['title']) in seed_keys-known]
        # These are explicitly requested public-source retries, not inference or
        # lost failure history. Earlier outcomes stay in the source checkpoint.
        state.setdefault('prior_unresolved',[]).extend(retry)
        state['unresolved']=[r for r in state.get('unresolved',[]) if r not in retry]
        state['visited']=[v for v in state.get('visited',[]) if v not in seed_keys-known]
        selected=[seed for seed in seeds if title_key(seed) not in known]
        selected_keys={title_key(seed) for seed in selected}
        state['pending']=selected+[title for title in state['pending'] if title_key(title) not in selected_keys]
        atomic_json(progress,state)
    inventory=discover_support(article['title'],anchor['content'],cutoff,resolver,
        max_pages=2000,progress_path=progress,request_budget=[args.support_requests],extra_titles=tuple(seeds),
        extra_namespaces={n['name'].replace('_',' '):n['id'] for n in namespaces})
    atomic_json(progress.with_suffix('.inventory.json'),inventory)
    print('Sources acquired:',len(records),'support pages:',len(inventory['supporting']),
        'unresolved:',len(inventory['unresolved']),'(source acquisition only; no inference)',flush=True)
    # One XML batch avoids launching a container once for every template/module.
    xml=ET.fromstring(mediawiki_xml(article,records))
    for item in inventory['supporting']:
        if hashlib.sha256(item['content'].encode()).hexdigest()!=item['sha256']:raise ValueError('Supporting source content changed before import.')
        source=dict(item,source_wiki=article['source_wiki'])
        support_article=dict(article,title=item['title'],source_page_id=item['source_page_id'],namespace_id=item['namespace_id'])
        exported=ET.fromstring(mediawiki_xml(support_article,[source]))
        xml.append(exported.find('{'+NS+'}page'))
    relative=Path('issue-sources')/(args.language+'-'+args.topic+'.xml')
    target=root/'imports'/relative;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(ET.tostring(xml,encoding='utf-8',xml_declaration=True))
    container=args.project+'-wiki-'+args.language+'-1'
    result=subprocess.run(['docker','exec',container,'php','maintenance/run.php','importDump','--username-prefix=Imported','/data/imports/'+relative.as_posix()],capture_output=True,text=True)
    if result.returncode:
        detail=result.stderr or result.stdout
        raise RuntimeError('Native import failed: '+detail[:700]+('\n…\n'+detail[-500:] if len(detail)>700 else ''))
    local_id,local_rows=fetch_local_page(runtime['languages'][args.language]['api_url'],article['title'])
    mappings=map_revisions(records,local_rows,local_id)
    if any(r['status']!='reconciled' for r in mappings):raise RuntimeError('Imported source/local content reconciliation is incomplete.')
    local={r['revid']:r for r in local_rows};sources={r['source_revision_id']:r for r in records}
    revisions=[]
    for mapping in mappings:
        row=local[mapping['local_revision_id']];source=sources[mapping['source_revision_id']]
        revisions.append(dict(local_revision_id=row['revid'],local_parent_id=row.get('parentid') or 0,
            source_revision_id=source['source_revision_id'],source_parent_id=source['source_parent_id'],
            timestamp=source['timestamp'],sha256=source['computed_sha256'],user=row.get('user'),
            source_user=(source.get('author') or {}).get('value'),comment=row.get('comment'),minor=row.get('minor',False),
            content_model=row.get('content_model'),source_url='https://'+args.language+'.wikipedia.org/w/index.php?oldid='+str(source['source_revision_id'])))
    path=root/'config'/args.language/(args.language+'.json')
    bundle=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(schema_version=1,language=args.language,source_wiki=article['source_wiki'],payload={'pages':[]})
    old=next((p for p in bundle['payload']['pages'] if p['source_page_id']==article['source_page_id']),None)
    if old:
        known={r['source_revision_id']:r for r in old['revisions']};known.update({r['source_revision_id']:r for r in revisions});revisions=list(known.values())
        bundle['payload']['pages'].remove(old)
    bundle['payload']['pages'].append(dict(local_page_id=local_id,source_page_id=article['source_page_id'],title=article['title'],
        source_anchor_revision_id=anchor['source_revision_id'],source_anchor_timestamp=anchor['timestamp'],
        history_complete=False,import_scope='explicit-issue-revisions',revisions=revisions,
        rendering_dependencies=dict(mode='current-at-import' if args.support_current else 'source-cutoff',cutoff=cutoff,state='complete' if inventory['complete'] else 'partial',unresolved=len(inventory['unresolved']),
            note='Article body stays at the exact source revision. Template revisions may be newer in current-at-import mode. Dynamic dependencies require parser verification.')))
    bundle['sha256']=sha256_bytes(canonical_json(bundle['payload']))
    atomic_json(path,bundle)
    atomic_json(directory/(args.topic+'-mapping.json'),mappings)
    # ImportDump preserves public revision timestamps. Refresh derived caches so
    # earlier negative template/module lookups cannot survive a successful import.
    for command in ([
        'docker','exec',container,'php','maintenance/run.php','purgeParserCache','--age','0'
    ], ['docker','restart',container]):
        refreshed=subprocess.run(command,capture_output=True,text=True)
        if refreshed.returncode:raise RuntimeError('Imported sources were saved, but native rendering cache refresh failed.')
    print('Imported and reconciled',args.language,article['title'],[(r['source_revision_id'],r['local_revision_id']) for r in revisions],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True);parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--topic',required=True);parser.add_argument('--language',choices=['en','fi','sv'],required=True)
    parser.add_argument('--revision',type=int,action='append',required=True)
    parser.add_argument('--support-requests',type=int,default=80)
    parser.add_argument('--namespace',action='append',default=[],help='Explicit additional source namespace to configure from verified siteinfo metadata.')
    parser.add_argument('--support-current',action='store_true',help='Explicitly import current template/module revisions, with their real timestamps; never substitute the historical article body.')
    parser.add_argument('--include-dependency',action='append',default=[],help='Explicit additional source page to acquire. Non-core namespaces also require --namespace.')
    parser.add_argument('--include-native-missing',action='store_true',help='Add actually missing native parser dependencies to this explicit import.')
    args=parser.parse_args()
    if len(args.revision)>100 or min(args.revision)<=0 or not 0<=args.support_requests<=2000:
        parser.error('Use 1–100 positive exact revisions and a bounded support budget of 0–2000 requests.')
    try:run(args)
    except Exception as error:
        print('Exact source import incomplete:',str(error),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())

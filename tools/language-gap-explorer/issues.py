"""Unified issue index. Explicit setup/backfill; browsing never prepares evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from core import connect

KINDS = {'contradiction':'Contradiction','framing':'Framing difference','coverage':'Missing context'}

def packed(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':'))

def identity(*parts):
    return hashlib.sha256(packed(parts).encode()).hexdigest()

def language_id(run,group):
    return identity('language',run,group)

def now():
    return datetime.now(timezone.utc).isoformat()

class PersistenceError(RuntimeError):
    pass

def init():
    statements=[
    """CREATE TABLE IF NOT EXISTS unified_issue (
      id CHAR(64) PRIMARY KEY, topic VARCHAR(24) NOT NULL, origin VARCHAR(24) NOT NULL,
      source_key VARCHAR(200) NOT NULL, title TEXT NOT NULL,
      KEY article_origin(topic,origin)) WITH SYSTEM VERSIONING""",
    """CREATE TABLE IF NOT EXISTS unified_assessment (
      id CHAR(64) PRIMARY KEY, topic VARCHAR(24) NOT NULL, mode VARCHAR(24) NOT NULL,
      assessed_at VARCHAR(40), payload LONGTEXT NOT NULL, KEY article_mode(topic,mode))""",
    """CREATE TABLE IF NOT EXISTS unified_observation (
      id CHAR(64) PRIMARY KEY, issue_id CHAR(64) NOT NULL, assessment_id CHAR(64) NOT NULL,
      stamp VARCHAR(40) NOT NULL, kind VARCHAR(50) NOT NULL, languages VARCHAR(40) NOT NULL,
      occurrence VARCHAR(100), payload LONGTEXT NOT NULL,
      KEY issue_stamp(issue_id,stamp), KEY assessment(assessment_id))""",
    """CREATE TABLE IF NOT EXISTS unified_coverage (
      id CHAR(64) PRIMARY KEY, topic VARCHAR(24) NOT NULL, origin VARCHAR(24) NOT NULL,
      scope LONGTEXT NOT NULL, state VARCHAR(20) NOT NULL, assessed_at VARCHAR(40),
      note TEXT, KEY article_scope(topic,origin)) WITH SYSTEM VERSIONING""",
    """CREATE TABLE IF NOT EXISTS unified_review (
      observation_id CHAR(64) NOT NULL, edition VARCHAR(10) NOT NULL, reviewed BOOLEAN NOT NULL,
      updated_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
      PRIMARY KEY(observation_id,edition)) WITH SYSTEM VERSIONING"""
    ,"""CREATE TABLE IF NOT EXISTS unified_native_review (
      wiki VARCHAR(100) NOT NULL, observation_id CHAR(64) NOT NULL,
      edition VARCHAR(12) NOT NULL, reviewed BOOLEAN NOT NULL,
      reviewer_id BIGINT UNSIGNED NOT NULL,
      updated_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
      PRIMARY KEY(wiki,observation_id,edition)) WITH SYSTEM VERSIONING"""
    ]
    with connect() as db,db.cursor() as c:
        for sql in statements:c.execute(sql)

def put_issue(c,iid,topic,origin,key,title):
    c.execute('SELECT title FROM unified_issue WHERE id=%s',(iid,));old=c.fetchone()
    if old:
        if old['title']!=title:c.execute('UPDATE unified_issue SET title=%s WHERE id=%s',(title,iid))
    else:c.execute('INSERT INTO unified_issue(id,topic,origin,source_key,title) VALUES(%s,%s,%s,%s,%s)',(iid,topic,origin,key,title))

def put_coverage(c,topic,origin,scope,state,assessed,note=''):
    cid=identity('coverage',topic,origin,scope)
    values=(state,assessed,note)
    c.execute('SELECT state,assessed_at,note FROM unified_coverage WHERE id=%s',(cid,));old=c.fetchone()
    if old:
        if tuple(old[k] for k in ('state','assessed_at','note'))!=values:
            c.execute('UPDATE unified_coverage SET state=%s,assessed_at=%s,note=%s WHERE id=%s',(*values,cid))
    else:c.execute('INSERT INTO unified_coverage(id,topic,origin,scope,state,assessed_at,note) VALUES(%s,%s,%s,%s,%s,%s,%s)',(cid,topic,origin,packed(scope),state,assessed,note))
    return cid

def scan_coverage(topic,ref,mode,state,note=''):
    try:
        with connect() as db,db.cursor() as c:
            put_coverage(c,topic,'flags',dict(mode=mode,lang=ref.lang,revision=ref.revision_id),state,now(),note)
    except Exception as error:
        raise PersistenceError('Issue storage is unavailable. No new scan should be started until it is restored.') from error

def store_scan(topic,ref,result,mode):
    """Persist successful evidence transactionally before overwriting the working cache."""
    if result.get('status')!='ok':raise ValueError('Only successful assessments can be indexed.')
    aid=result.get('_issue_assessment') or identity('scan',uuid.uuid4().hex)
    assessed=result.get('_issue_assessed_at') or now()
    result=dict(result,_issue_assessment=aid,_issue_assessed_at=assessed)
    try:
        with connect() as db:
            db.begin()
            try:
                with db.cursor() as c:
                    c.execute('INSERT IGNORE INTO unified_assessment(id,topic,mode,assessed_at,payload) VALUES(%s,%s,%s,%s,%s)',(aid,topic,mode,assessed,packed(dict(ref=ref.__dict__,result=result))))
                    for index,flag in enumerate(result.get('flags',[])):
                        # Never join separate detector classes or languages by their prose title.
                        key=identity(mode,ref.lang,ref.revision_id,ref.parent_id,flag.get('kind'),flag.get('side'),flag.get('anchor_text'),flag.get('anchor_start'),flag.get('id') if not flag.get('anchor_text') else None)
                        iid=identity('flags',topic,key)
                        put_issue(c,iid,topic,'flags',key,flag.get('title') or flag.get('kind','Detector suggestion'))
                        oid=identity(iid,aid,index)
                        payload=dict(flag=flag,revision=ref.revision_id,source_stamp=ref.timestamp,mode=mode,source_id=flag.get('id'))
                        c.execute('INSERT IGNORE INTO unified_observation(id,issue_id,assessment_id,stamp,kind,languages,occurrence,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(oid,iid,aid,ref.timestamp or '',flag.get('kind','UNKNOWN'),ref.lang,None,packed(payload)))
                    put_coverage(c,topic,'flags',dict(mode=mode,lang=ref.lang,revision=ref.revision_id),'partial' if result.get('partial') else 'completed',assessed)
                db.commit()
            except Exception:
                db.rollback();raise
    except Exception as error:
        raise PersistenceError('The scan completed but issue storage failed. The previous evidence was preserved; retry saving before re-scanning.') from error
    return result

def backfill(topic=None):
    """Read-only source adapters; only derived unified tables are written."""
    counts=dict(language=0,snapshot=0,flags=0)
    with connect() as source,source.cursor() as c:
        c.execute('SELECT id,topic,status,summary,updated FROM paired_run WHERE summary IS NOT NULL'+(' AND topic=%s' if topic else ''), (topic,) if topic else ())
        runs=list(c.fetchall())
    with connect() as db:
        for run in runs:
            summary=json.loads(run['summary']);rows={r['id']:r for r in summary.get('rows',[])}
            from question_titles import labels
            names=labels(run['topic'],list(rows))
            languages=summary.get('topic',{}).get('languages',[])
            assessed=str(run['updated'])
            with connect() as source,source.cursor() as c:
                c.execute('SELECT id,topic_id,stamp,kind,payload FROM paired_occurrence WHERE run_id=%s',(run['id'],));occurrences=list(c.fetchall())
            db.begin()
            try:
                with db.cursor() as c:
                    aid=identity('language-run',run['id'])
                    c.execute('INSERT IGNORE INTO unified_assessment(id,topic,mode,assessed_at,payload) VALUES(%s,%s,%s,%s,%s)',(aid,run['topic'],'language',assessed,packed(dict(run=run['id'],source='paired_run'))))
                    for row in occurrences:
                        data=json.loads(row['payload']);evidence=data.get('evidence',[])
                        if len(evidence)<2:continue
                        langs=sorted({e['lang'] for e in evidence});iid=language_id(run['id'],row['topic_id'])
                        named=names.get(row['topic_id'],{})
                        title=(named.get('title') if named.get('status')=='accepted' else None) or rows.get(row['topic_id'],{}).get('title') or data.get('question') or 'Language discrepancy'
                        put_issue(c,iid,run['topic'],'language',run['id']+':'+row['topic_id'],title)
                        oid=identity('occurrence',row['id'])
                        payload=dict(run=run['id'],group=row['topic_id'],stamp=row['stamp'],source_hash=identity(data),source_id=row['id'],scope='historical')
                        c.execute('INSERT IGNORE INTO unified_observation(id,issue_id,assessment_id,stamp,kind,languages,occurrence,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(oid,iid,aid,row['stamp'],row['kind'],','.join(langs),row['id'],packed(payload)))
                        counts['language']+=1
                    observations=summary.get('observations') or [dict(stamp=s,state='unknown') for s in sorted({o['stamp'] for o in occurrences})]
                    for observation in observations:
                        state={'complete':'completed','ready':'completed','running':'running','failed':'failed'}.get(observation.get('state'),'not assessed')
                        put_coverage(c,run['topic'],'language',dict(run=run['id'],stamp=observation['stamp'],languages=languages),state,assessed,'Partial or unknown comparisons are not agreement.' if state=='not assessed' else '')
                db.commit()
            except Exception:db.rollback();raise
    # Snapshot findings have no historical lifetime; import their own identities.
    with connect() as db,db.cursor() as c:
        c.execute("SELECT r.id,r.topic,r.updated,r.status,g.id group_id,g.findings FROM review_run r JOIN review_group g ON g.run_id=r.id WHERE g.status='done'"+(' AND r.topic=%s' if topic else ''),(topic,) if topic else ())
        snapshots=list(c.fetchall())
    for row in snapshots:
        with connect() as db,db.cursor() as c:
            aid=identity('snapshot',row['id']);assessed=str(row['updated'])
            c.execute('INSERT IGNORE INTO unified_assessment(id,topic,mode,assessed_at,payload) VALUES(%s,%s,%s,%s,%s)',(aid,row['topic'],'snapshot',assessed,packed(dict(run=row['id']))))
            for index,finding in enumerate(json.loads(row['findings'] or '[]')):
                kind=finding.get('category','uncertain')
                if kind not in ('conflict','coverage','framing'):continue
                evidence=finding.get('evidence',[]);langs=sorted({e['lang'] for e in evidence})
                iid=identity('snapshot',row['id'],row['group_id'],finding.get('id',index));oid=identity(iid,'snapshot')
                put_issue(c,iid,row['topic'],'language','snapshot:'+row['id']+':'+row['group_id']+':'+str(index),finding.get('title','Snapshot language discrepancy'))
                c.execute('INSERT IGNORE INTO unified_observation(id,issue_id,assessment_id,stamp,kind,languages,occurrence,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(oid,iid,aid,'',{'conflict':'contradiction'}.get(kind,kind),','.join(langs),None,packed(dict(scope='snapshot',finding=finding))))
                counts['snapshot']+=1
            put_coverage(c,row['topic'],'language',dict(snapshot=row['id']), 'completed' if row['status']=='done' else 'not assessed',assessed,'Snapshot assessment; historical lifetime unknown.')
    from revision_text import cache_root
    from flags_tab import RevisionRef
    root=cache_root()
    for directory,mode in [('audits','revision'),('pages','page')]:
        for path in sorted((root/directory).glob('*.json')):
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('status','ok')!='ok':continue
            match=re.fullmatch(r'([a-z-]+)-(\d+)',path.stem)
            if not match:continue
            lang,revision=match.group(1),int(match.group(2))
            revpath=root/'revisions'/path.name
            record=json.loads(revpath.read_text(encoding='utf-8')) if revpath.exists() else {}
            title=record.get('title');source_topic=None
            with connect() as db,db.cursor() as c:
                if title:
                    c.execute('SELECT wikidata_id FROM article WHERE lang=%s AND title=%s',(lang,title));a=c.fetchone();source_topic=a['wikidata_id'] if a else None
                if not source_topic:
                    c.execute("SELECT r.topic FROM paired_occurrence o JOIN paired_run r ON r.id=o.run_id WHERE JSON_SEARCH(o.payload,'one',%s,NULL,'$.evidence[*].revision') IS NOT NULL LIMIT 1",(str(revision),));a=c.fetchone();source_topic=a['topic'] if a else None
            if not source_topic or (topic and topic!=source_topic):continue
            ref=RevisionRef(lang,revision,title or source_topic,record.get('timestamp',''),f'https://{lang}.wikipedia.org/w/index.php?oldid={revision}',record.get('parent_id'))
            # Existing cache import is stable, even without scanner metadata.
            data=dict(data,status='ok');data.setdefault('_issue_assessment',identity('cache',source_topic,lang,revision,mode,data))
            data.setdefault('_issue_assessed_at',datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
            store_scan(source_topic,ref,data,mode);counts['flags']+=1
    return counts

def latest_sets(topic,args):
    """Select whole assessment sets, never the last sighting of every past issue."""
    with connect() as db,db.cursor() as c:
        c.execute('SELECT id,mode,assessed_at,payload FROM unified_assessment WHERE topic=%s ORDER BY assessed_at DESC,id',(topic,));assessments=list(c.fetchall())
        language=None;snapshot=None;flags={}
        selected=args.getlist('languages') if hasattr(args,'getlist') else []
        for assessment in assessments:
            data=json.loads(assessment['payload']);mode=assessment['mode']
            if mode=='language' and language is None:
                if args.get('run') and data['run']!=args['run']:continue
                c.execute('SELECT summary FROM paired_run WHERE id=%s',(data['run'],));source=c.fetchone()
                if not source:continue
                summary=json.loads(source['summary'])
                if selected and not set(selected)<=set(summary.get('topic',{}).get('languages',[])):continue
                stamps=[o['stamp'] for o in summary.get('observations',[]) if o.get('state') in ('complete','partial','ready')]
                if not stamps:
                    c.execute('SELECT MAX(stamp) stamp FROM unified_observation WHERE assessment_id=%s',(assessment['id'],));last=c.fetchone()['stamp']
                else:last=max(stamps)
                language=dict(assessment=assessment['id'],run=data['run'],stamp=args.get('stamp') or last,assessed_at=assessment['assessed_at'])
            elif mode=='snapshot' and snapshot is None:snapshot=assessment
            elif mode in ('revision','page'):
                ref=data.get('ref',{});key=(mode,ref.get('lang'));rank=(ref.get('timestamp') or '',int(ref.get('revision_id') or 0),assessment['assessed_at'] or '',assessment['id'])
                if key not in flags or rank>flags[key][0]:flags[key]=(rank,assessment)
        chosen=[]
        if args.get('run') and language is None:raise LookupError('The requested analysis run has not been indexed. No other run or snapshot was substituted.')
        if args.get('scope')=='snapshot':
            if snapshot:chosen.append(('snapshot',snapshot['id'],None))
        elif language:chosen.append(('language',language['assessment'],language['stamp']))
        elif snapshot:chosen.append(('snapshot',snapshot['id'],None))
        chosen.extend((a['mode'],a['id'],None) for _,a in flags.values())
    return chosen,language

def list_issues(topic,args,review_scope=None):
    edition=args.get('lang','en');history=args.get('view')=='history'
    clauses=['i.topic=%s'];values=[topic];selected_set=None
    if not history:
        chosen,selected_set=latest_sets(topic,args)
        options=[]
        for mode,aid,stamp in chosen:
            option='(o.assessment_id=%s';values.append(aid)
            if stamp is not None:option+=' AND o.stamp=%s';values.append(stamp)
            options.append(option+')')
        clauses.append('('+' OR '.join(options)+')' if options else '1=0')
    if history and args.get('run'):
        clauses.append("(a.mode IN ('revision','page') OR (a.mode='language' AND JSON_UNQUOTE(JSON_EXTRACT(a.payload,'$.run'))=%s))")
        values.append(args['run'])
    for key,column in [('origin','i.origin'),('kind','o.kind'),('scope','a.mode')]:
        if args.get(key):clauses.append(('BINARY ' if key=='kind' else '')+column+'=%s');values.append(args[key])
    kinds=args.getlist('kinds') if hasattr(args,'getlist') else []
    if kinds:
        if len(kinds)>40 or any(not re.fullmatch(r'[A-Za-z_]{1,50}',k) for k in kinds):raise ValueError('Choose valid classifications.')
        clauses.append('BINARY o.kind IN ('+','.join(['%s']*len(kinds))+')');values.extend(kinds)
    if args.get('language'):
        clauses.append('FIND_IN_SET(%s,o.languages)>0');values.append(args['language'])
    selected=args.getlist('languages') if hasattr(args,'getlist') else args.get('languages',[])
    if selected:
        if not isinstance(selected,list) or not set(selected)<={'en','fi','sv','ru'}:raise ValueError('Choose supported editions.')
        for excluded in sorted({'en','fi','sv','ru'}-set(selected)):
            clauses.append('FIND_IN_SET(%s,o.languages)=0');values.append(excluded)
    for key,operator in [('from','>='),('to','<=')]:
        if args.get(key):
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args[key]):raise ValueError('Choose valid dates.')
            clauses.append('LEFT(o.stamp,10)'+operator+'%s');values.append(args[key])
    if args.get('q'):
        clauses.append('(i.title LIKE %s OR o.kind LIKE %s)');values.extend(['%'+args['q'].strip()[:200]+'%']*2)
    review_table='unified_native_review' if review_scope else 'unified_review'
    review_join=' AND r.wiki=%s' if review_scope else ''
    review_values=[edition,review_scope] if review_scope else [edition]
    base="""SELECT i.*,o.id observation,o.assessment_id,o.stamp,o.kind,o.languages,o.occurrence,
       a.assessed_at,a.mode,COALESCE(r.reviewed,0) reviewed,
       ROW_NUMBER() OVER(PARTITION BY i.id ORDER BY o.stamp DESC,a.assessed_at DESC,
         CASE BINARY o.kind WHEN 'contradiction' THEN 3 WHEN 'framing' THEN 2 ELSE 1 END DESC,o.id) rn
       FROM unified_issue i JOIN unified_observation o ON o.issue_id=i.id
       JOIN unified_assessment a ON a.id=o.assessment_id
       LEFT JOIN """+review_table+""" r ON r.observation_id=o.id AND r.edition=%s"""+review_join+" WHERE "+' AND '.join(clauses)
    conditions=[] if history else ['rn=1']
    if args.get('review') in ('reviewed','unreviewed'):
        conditions.append('reviewed='+('1' if args['review']=='reviewed' else '0'))
    suffix=(' WHERE '+' AND '.join(conditions)) if conditions else ''
    try:page=max(1,int(args.get('page','1')))
    except ValueError:raise ValueError('Invalid issue page.')
    with connect() as db,db.cursor() as c:
        c.execute('SELECT COUNT(*) n FROM ('+base+') results'+suffix,review_values+values);total=c.fetchone()['n']
        c.execute('SELECT origin,COUNT(*) n FROM ('+base+') results'+suffix+' GROUP BY origin',review_values+values);breakdown={r['origin']:r['n'] for r in c.fetchall()}
        c.execute('SELECT * FROM ('+base+') results'+suffix+' ORDER BY stamp DESC,assessed_at DESC,id,observation LIMIT 50 OFFSET %s',review_values+values+[(page-1)*50]);rows=list(c.fetchall())
        c.execute('SELECT origin,scope,state,assessed_at,note FROM unified_coverage WHERE topic=%s ORDER BY assessed_at DESC LIMIT 100',(topic,));coverage=list(c.fetchall())
        c.execute('SELECT state,COUNT(*) n FROM unified_coverage WHERE topic=%s GROUP BY state',(topic,));coverage_counts={r['state']:r['n'] for r in c.fetchall()}
        c.execute('SELECT DISTINCT BINARY kind kind FROM unified_observation o JOIN unified_issue i ON i.id=o.issue_id WHERE i.topic=%s ORDER BY BINARY kind',(topic,));kinds=[r['kind'].decode('utf-8') if isinstance(r['kind'],bytes) else r['kind'] for r in c.fetchall()]
    for row in rows:
        row['label']=KINDS.get(row['kind'],row['kind'].replace('_',' ').title());row['languages']=row['languages'].split(',')
    for item in coverage:item['scope']=json.loads(item['scope'])
    return dict(issues=rows,total=total,page=page,pages=max(1,(total+49)//50),coverage=coverage,coverage_counts=coverage_counts,kinds=kinds,breakdown=breakdown,selected_set=selected_set)

def get_observation(topic,iid,observation=None,occurrence=None,edition='en',review_scope=None):
    clauses=['i.topic=%s','i.id=%s'];values=[topic,iid]
    if observation:clauses.append('o.id=%s');values.append(observation)
    if occurrence:clauses.append('o.occurrence=%s');values.append(occurrence)
    review_table='unified_native_review' if review_scope else 'unified_review'
    review_join=' AND r.wiki=%s' if review_scope else ''
    review_values=[edition,review_scope] if review_scope else [edition]
    with connect() as db,db.cursor() as c:
        c.execute("""SELECT i.*,o.id observation,o.assessment_id,o.stamp,o.kind,o.languages,o.occurrence,
          o.payload observation_payload,a.payload assessment_payload,a.mode,a.assessed_at,
          COALESCE(r.reviewed,0) reviewed FROM unified_issue i JOIN unified_observation o ON o.issue_id=i.id
          JOIN unified_assessment a ON a.id=o.assessment_id LEFT JOIN """+review_table+""" r ON r.observation_id=o.id AND r.edition=%s"""+review_join+"""
          WHERE """+' AND '.join(clauses)+' ORDER BY o.stamp DESC,a.assessed_at DESC,o.id LIMIT 1',review_values+values)
        row=c.fetchone()
        if not row:raise LookupError('That exact issue observation is unavailable. No other evidence was substituted.')
        payload=json.loads(row.pop('observation_payload'));assessment=json.loads(row.pop('assessment_payload'))
        if row['mode']=='language':
            c.execute('SELECT payload FROM paired_occurrence WHERE id=%s AND run_id=%s AND topic_id=%s AND stamp=%s',(row['occurrence'],payload['run'],payload['group'],payload['stamp']));source=c.fetchone()
            if not source or identity(json.loads(source['payload']))!=payload['source_hash']:raise LookupError('The archived source evidence is unavailable or changed.')
            from evidence_highlights import enrich
            row['evidence']=enrich(topic,payload['group'],dict(json.loads(source['payload']),id=row['occurrence']));row['context']=payload
        elif row['mode']=='snapshot':row['evidence']=payload['finding'];row['context']=payload
        else:row['evidence']=assessment;row['context']=payload
        c.execute('SELECT id,stamp,occurrence,kind FROM unified_observation WHERE issue_id=%s ORDER BY stamp DESC,id LIMIT 500',(iid,));row['observations']=list(c.fetchall())
    row['languages']=row['languages'].split(',');row['label']=KINDS.get(row['kind'],row['kind'].replace('_',' ').title())
    return row

def resolve_legacy(topic,args):
    if not all(args.get(k) for k in ('run','group','stamp')):raise ValueError('The historical issue identity is incomplete.')
    iid=language_id(args['run'],args['group'])
    values=[topic,iid,args['stamp']];extra=''
    if args.get('occurrence'):extra=' AND o.occurrence=%s';values.append(args['occurrence'])
    with connect() as db,db.cursor() as c:
        c.execute('SELECT o.id,o.occurrence,o.languages,o.kind FROM unified_observation o JOIN unified_issue i ON i.id=o.issue_id WHERE i.topic=%s AND i.id=%s AND o.stamp=%s'+extra+' ORDER BY o.id',values);rows=list(c.fetchall())
    selected=args.getlist('languages') if hasattr(args,'getlist') else []
    if selected:rows=[r for r in rows if set(r['languages'].split(','))<=set(selected)]
    if not rows:raise LookupError('This exact historical issue has not been indexed or does not match the selected editions.')
    if args.get('occurrence'):return iid,rows[0]
    # Use the established supporting-occurrence selector only when no exact one was supplied.
    rank={'contradiction':3,'framing':2,'coverage':1}
    rows.sort(key=lambda r:(-rank.get(r['kind'],0),args.get('lang','en') not in r['languages'].split(','),r['id']))
    return iid,rows[0]

def mark_reviewed(topic,iid,oid,edition,reviewed):
    row=get_observation(topic,iid,oid,edition=edition)
    if edition not in ('en','fi','sv','ru'):raise ValueError('Choose a valid article edition.')
    with connect() as db,db.cursor() as c:
        c.execute('SELECT reviewed FROM unified_review WHERE observation_id=%s AND edition=%s',(oid,edition));old=c.fetchone()
        if old is None or bool(old['reviewed'])!=reviewed:
            c.execute('INSERT INTO unified_review(observation_id,edition,reviewed) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE reviewed=VALUES(reviewed)',(row['observation'],edition,reviewed))
    return dict(observation=oid,edition=edition,reviewed=reviewed)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['init','backfill']);parser.add_argument('--topic');args=parser.parse_args()
    print(init() if args.command=='init' else packed(backfill(args.topic)))

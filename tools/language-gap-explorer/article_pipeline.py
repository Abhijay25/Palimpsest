"""Explicit, article-scoped preparation and resumable pilot/corpus queue.

No worker starts on page reads. V1 Winter War runs remain unchanged and readable.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta,timezone
from itertools import combinations
import json
import os
from pathlib import Path
import re
import shutil
import threading

from core import ROOT,connect
import paired_history as paired
import historical_divergence as storage

VERSION='article-symmetric-v2'
GROUP_POLICY=VERSION+'-groups'
LANGUAGES=('en','fi','sv')
_model_lock=threading.Lock()
# Explicitly verified local-dataset IDs; displayed titles always come from article.
SHOWCASE_ARTICLES=(
    ('Q134949','Winter War'),('Q122100','Continuation War'),('Q211855','Finnish Civil War'),
    ('Q154940','Lapland War'),('Q202808','History of Finland'),('Q62633','Grand Duchy of Finland'),
    ('Q12375230','Finland under Swedish rule'),('Q736268','Finnish War'),
    ('Q620854','Treaty of Tartu (Finland–Russia)'),('Q1130792','Treaty of Fredrikshamn'),
    ('Q823175','Finlandization'),('Q2920215',"Finland's language strife"),
    ('Q2328052','Russification of Finland'),('Q1799569','Fennoman movement'),
    ('Q2573930','Svecoman movement'),('Q27916528','Independence of Finland'),
    ('Q175720','Greater Finland'),('Q42901487','Swedish colonisation of Finland'),
    ('Q615902','Kingdom of Finland (1918)'),('Q2606233','Tornedalians'))


class DiskGuardError(RuntimeError):pass


def safe_error(error):
    """Provider messages are already scrubbed; redact again before queue/log use."""
    label=type(error).__name__
    if label not in ('APIError','BudgetError','DiskGuardError'):return label
    message=re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',str(error)).replace(str(ROOT),'[research root]')
    return label+': '+' '.join(message.split())[:350]


def ensure_disk_space():
    free=shutil.disk_usage(ROOT).free
    if free<512*1024*1024:raise DiskGuardError('Preparation paused below the existing 512 MiB disk guard.')
    return free


@dataclass(frozen=True)
class EditionAnchor:
    lang:str
    page_id:int
    revision:int
    title:str
    stamp:str


@dataclass(frozen=True)
class ArticleContext:
    topic:str
    title:str
    anchors:tuple
    mode:str='history'
    since:str='2020-01-01'
    workers:int=6

    def __post_init__(self):
        if not re.fullmatch(r'Q\d{1,15}',self.topic):raise ValueError('Invalid article identity.')
        langs=tuple(a.lang for a in self.anchors)
        if len(langs)<2 or len(set(langs))!=len(langs) or not set(langs)<=set(LANGUAGES):raise ValueError('Choose two or three available dataset editions.')
        if self.mode not in ('snapshot','history'):raise ValueError('Choose snapshot or history mode.')
        datetime.strptime(self.since,'%Y-%m-%d')
        if not 1<=self.workers<=6:raise ValueError('Use one to six assessment workers.')

    @property
    def languages(self):return tuple(sorted(a.lang for a in self.anchors))
    @property
    def cutoff(self):return min(a.stamp for a in self.anchors)
    @property
    def cache(self):return ROOT/'data'/'article-history'/self.topic
    def configuration(self):
        return dict(topic=self.topic,title=self.title,anchors=[asdict(a) for a in sorted(self.anchors,key=lambda a:a.lang)],
                    languages=list(self.languages),mode=self.mode,since=self.since,version=VERSION)


def article_context(topic,languages=None,mode='history',since='2020-01-01',workers=6):
    with connect() as db,db.cursor() as c:
        c.execute('SELECT lang,page_id,rev_id,title,date_modified FROM article WHERE wikidata_id=%s ORDER BY lang',(topic,));rows=list(c.fetchall())
    chosen=set(languages or [r['lang'] for r in rows]);rows=[r for r in rows if r['lang'] in chosen]
    if chosen!={r['lang'] for r in rows}:raise ValueError('A requested edition is not present in the dataset.')
    anchors=tuple(EditionAnchor(r['lang'],int(r['page_id']),int(r['rev_id']),r['title'],r['date_modified']) for r in rows)
    title=next((r['title'] for r in rows if r['lang']=='en'),rows[0]['title'] if rows else topic)
    return ArticleContext(topic,title,anchors,mode,since,workers)


def init():
    paired.init()
    statements=[
        '''CREATE TABLE IF NOT EXISTS article_feature_scope(article VARCHAR(24),version VARCHAR(80),pair_id CHAR(64),
           PRIMARY KEY(article,version,pair_id)) CHARACTER SET utf8mb4''',
        '''CREATE TABLE IF NOT EXISTS article_semantic_topic(id CHAR(64) PRIMARY KEY,article VARCHAR(24),version VARCHAR(80),
           representative CHAR(64),payload LONGTEXT,KEY article_version(article,version)) CHARACTER SET utf8mb4''',
        '''CREATE TABLE IF NOT EXISTS article_assignment(article VARCHAR(24),version VARCHAR(80),pair_id CHAR(64),topic_id CHAR(64),
           PRIMARY KEY(article,version,pair_id)) CHARACTER SET utf8mb4''',
        '''CREATE TABLE IF NOT EXISTS article_checkpoint(run_id CHAR(64),stamp VARCHAR(32),status VARCHAR(24),
           revision_tuple CHAR(64),reused_from VARCHAR(32),error VARCHAR(100),PRIMARY KEY(run_id,stamp)) CHARACTER SET utf8mb4''',
        '''CREATE TABLE IF NOT EXISTS article_preparation_queue(id CHAR(64) PRIMARY KEY,article VARCHAR(24),mode VARCHAR(16),
           configuration LONGTEXT,status VARCHAR(24),priority INT DEFAULT 100,run_id CHAR(64),error VARCHAR(100),
           updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,KEY work(status,priority)) CHARACTER SET utf8mb4''']
    with connect() as db,db.cursor() as c:
        for statement in statements:c.execute(statement)


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+f'.{os.getpid()}.{threading.get_ident()}.part')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def source_text(context,lang,revision):
    """Reuse existing revision files without changing any global cache directory."""
    candidates=[context.cache/f'{lang}-{revision}.txt',storage.CACHE/f'{lang}-{revision}.txt',ROOT/'data'/'showcase-history'/f'{lang}-{revision}.txt']
    for path in candidates:
        if path.is_file():return path.read_text(encoding='utf-8')
    ensure_disk_space()
    from showcase_history import revision as fetch_revision
    text=fetch_revision(lang,revision);path=candidates[0];path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+f'.{os.getpid()}.{threading.get_ident()}.part');temporary.write_text(text,encoding='utf-8');temporary.replace(path);return text


def acquire_manifest(context):
    """Enumerate revision metadata in pages, then select month as-ofs locally."""
    from showcase_history import api
    cache=context.cache/('manifest-'+storage.digest(context.configuration())+'.json')
    if cache.is_file():return json.loads(cache.read_text(encoding='utf-8'))
    manifest=dict(anchors={a.lang:dict(page_id=a.page_id,anchor_rev=a.revision,title=a.title,stamp=a.stamp) for a in context.anchors},history={},gaps=[])
    for anchor in context.anchors:
        if context.mode=='snapshot':
            result=api(anchor.lang,dict(action='query',prop='revisions',pageids=anchor.page_id,rvstart=context.cutoff,rvdir='older',rvlimit=1,rvprop='ids|timestamp'))
            manifest['history'][anchor.lang]=result['query']['pages'][0].get('revisions',[]);continue
        rows=[];continuation={}
        while True:
            result=api(anchor.lang,dict(action='query',prop='revisions',pageids=anchor.page_id,rvstart=context.cutoff,rvend=context.since+'T00:00:00Z',rvdir='older',rvlimit=500,rvprop='ids|timestamp',**continuation))
            rows.extend(result['query']['pages'][0].get('revisions',[]))
            continuation=result.get('continue',{})
            if not continuation:break
        baseline=api(anchor.lang,dict(action='query',prop='revisions',pageids=anchor.page_id,rvstart=context.since+'T00:00:00Z',rvdir='older',rvlimit=1,rvprop='ids|timestamp'))
        rows.extend(baseline['query']['pages'][0].get('revisions',[]))
        manifest['history'][anchor.lang]=sorted({r['revid']:r for r in rows if r['timestamp']<=context.cutoff and r['revid']<=anchor.revision}.values(),key=lambda r:(r['timestamp'],r['revid']))
    manifest['complete']=True;_write(cache,manifest);return manifest


def checkpoint_schedule(context,manifest):
    cutoff=context.cutoff;points={cutoff}
    if context.mode=='history':
        date=datetime.strptime(context.since,'%Y-%m-%d').replace(tzinfo=timezone.utc,day=1)
        while date.isoformat().replace('+00:00','Z')<=cutoff:
            nxt=date.replace(year=date.year+1,month=1) if date.month==12 else date.replace(month=date.month+1)
            stamp=(nxt-timedelta(seconds=1)).isoformat().replace('+00:00','Z')
            if stamp<=cutoff:points.add(stamp)
            date=nxt
        # The most recent real edited dates, never manufactured hourly points.
        by_day={}
        for history in manifest['history'].values():
            for r in history:
                if context.since+'T00:00:00Z'<=r['timestamp']<=cutoff:by_day[r['timestamp'][:10]]=max(by_day.get(r['timestamp'][:10],''),r['timestamp'])
        points.update(by_day[d] for d in sorted(by_day)[-20:])
    histories={l:sorted(manifest['history'].get(l,[]),key=lambda r:r['timestamp']) for l in context.languages};checkpoints=[]
    for stamp in sorted(points):
        revisions={};missing=[]
        for lang,history in histories.items():
            index=bisect_right([r['timestamp'] for r in history],stamp)-1
            if index<0:missing.append(lang)
            else:revisions[lang]=history[index]
        checkpoints.append(dict(stamp=stamp,revisions=revisions,state='unknown' if missing else 'pending',missing=missing,sampled=True,
            revision_tuple=storage.digest(sorted((l,r['revid']) for l,r in revisions.items()))))
    return checkpoints


def run_configuration(context,checkpoints):
    return dict(**context.configuration(),window=[p['stamp'] for p in checkpoints],
                revision_tuples=[dict(stamp=p['stamp'],revisions=sorted((l,r['revid']) for l,r in p['revisions'].items()),missing=p['missing']) for p in checkpoints])


def assign_topics(context,pairs,verdicts):
    """Serialize representative updates for one article, not the whole corpus."""
    name='article_groups_'+context.topic
    with connect() as db,db.cursor() as c:
        c.execute('SELECT GET_LOCK(%s,180) locked',(name,))
        if c.fetchone()['locked']!=1:raise RuntimeError('Article grouping worker is busy.')
        try:return _assign_topics(context,pairs,verdicts)
        finally:c.execute('SELECT RELEASE_LOCK(%s)',(name,))


def _assign_topics(context,pairs,verdicts):
    """Existing representative-star grouping, with an explicit article boundary."""
    actionable={k:p for k,p in pairs.items() if verdicts[k]['kind'] in ('contradiction','framing','coverage')}
    if not actionable:return {}
    scope=(context.topic,GROUP_POLICY);ids=list(actionable);assigned={};payloads={}
    with connect() as db,db.cursor() as c:
        c.execute('SELECT pair_id,topic_id FROM article_assignment WHERE article=%s AND version=%s AND pair_id IN ('+','.join(['%s']*len(ids))+')',[*scope,*ids]);assigned={r['pair_id']:r['topic_id'] for r in c.fetchall()}
        for identity,pair in actionable.items():
            payloads[identity]=paired.representative(pair)
            c.execute('INSERT IGNORE INTO paired_feature VALUES(%s,%s,%s)',(identity,paired.feature(pair),json.dumps(payloads[identity],ensure_ascii=False)))
            c.execute('INSERT IGNORE INTO article_feature_scope VALUES(%s,%s,%s)',(*scope,identity))
        c.execute('SELECT * FROM article_semantic_topic WHERE article=%s AND version=%s',scope);topics={r['representative']:r for r in c.fetchall()}
    checks={};neighbors={};cases={}
    for identity in (k for k in ids if k not in assigned):
        with connect() as db,db.cursor() as c:
            c.execute('SELECT embedding FROM paired_feature WHERE id=%s',(identity,));vector=c.fetchone()['embedding']
            c.execute('''SELECT f.id,f.payload FROM paired_feature f JOIN article_feature_scope s ON s.pair_id=f.id
                WHERE s.article=%s AND s.version=%s AND f.id<>%s ORDER BY VEC_DISTANCE_COSINE(f.embedding,%s)+0 LIMIT 8''',(*scope,identity,vector));near=list(c.fetchall())
            c.execute('''SELECT f.id,f.payload FROM paired_feature f JOIN article_semantic_topic t ON t.representative=f.id
                WHERE t.article=%s AND t.version=%s AND f.id<>%s ORDER BY VEC_DISTANCE_COSINE(f.embedding,%s)+0 LIMIT 8''',(*scope,identity,vector));near=list({r['id']:r for r in near+list(c.fetchall())}.values())
            neighbors[identity]=[r['id'] for r in near]
            for row in near:
                key=storage.digest([GROUP_POLICY,context.topic,sorted([identity,row['id']])]);c.execute('SELECT probability FROM paired_group_check WHERE id=%s',(key,));old=c.fetchone()
                if old:checks[key]=old['probability']
                else:cases[key]=(key,payloads[identity],json.loads(row['payload']))
    batches=[list(cases.values())[i:i+20] for i in range(0,len(cases),20)]
    with ThreadPoolExecutor(max_workers=context.workers) as pool:
        futures={pool.submit(paired.group_check_batch,b,GROUP_POLICY+':'+context.topic):b for b in batches}
        for future in as_completed(futures):
            try:checks.update(future.result())
            except Exception as error:
                print(context.topic,'grouping batch unavailable:',safe_error(error),flush=True)
                with connect() as db,db.cursor() as c:
                    for key,_,_ in futures[future]:
                        checks[key]=None
                        # NULL means unassessed, never a negative identity judgment.
                        c.execute('INSERT IGNORE INTO paired_group_check VALUES(%s,NULL)',(key,))
    for identity in sorted(neighbors):
        choices=[];unknown=False
        for candidate in neighbors[identity]:
            if candidate not in topics:continue
            probability=checks.get(storage.digest([GROUP_POLICY,context.topic,sorted([identity,candidate])]),0)
            if probability is None:unknown=True
            elif probability>=.88:choices.append((probability,candidate))
        if choices:topic_id=topics[max(choices)[1]]['id']
        elif unknown:continue  # Defer possible duplicates rather than inflate counts.
        else:
            topic_id=storage.digest([GROUP_POLICY,context.topic,'semantic-topic',identity]);pair=actionable[identity];question=verdicts[identity]['question']
            payload=dict(title=paired.QUESTIONS.get(question,paired.QUESTIONS['account'])+' · '+pair['a']['section']+' / '+pair['b']['section'],question=question,representative=payloads[identity],article=context.topic,grouping='article-scoped fixed representative, no fixed K')
            with connect() as db,db.cursor() as c:c.execute('INSERT IGNORE INTO article_semantic_topic VALUES(%s,%s,%s,%s,%s)',(topic_id,*scope,identity,json.dumps(payload,ensure_ascii=False)))
            topics[identity]=dict(id=topic_id,representative=identity)
        assigned[identity]=topic_id
        with connect() as db,db.cursor() as c:c.execute('INSERT IGNORE INTO article_assignment VALUES(%s,%s,%s,%s)',(*scope,identity,topic_id))
    return assigned


def group_metadata(identity):
    with connect() as db,db.cursor() as c:
        c.execute('SELECT payload FROM article_semantic_topic WHERE id=%s',(identity,));row=c.fetchone()
        if not row:c.execute('SELECT payload FROM paired_topic WHERE id=%s',(identity,));row=c.fetchone()
    return json.loads(row['payload']) if row else None


def stage_names(result,progress,final=False):
    """Worker-only durable naming/search staging; never invokes a provider."""
    count=len(result['rows'])
    if count<=progress.get('naming_attempted_groups',0) and not final:return
    progress['naming_attempted_groups']=count
    try:
        from question_titles import stage
        staged=stage(result['topic']['id'],run=result['run'],languages=result['topic']['languages'])
        pending=staged.get('pending_batches',0) if isinstance(staged,dict) else len(staged[1])
        progress.update(naming_staged_groups=count,naming_pending=bool(pending),naming_pending_batches=pending,naming_error=None)
    except Exception as error:
        progress.update(naming_pending=True,naming_error=type(error).__name__)


def publish(run_id,base,progress,hook=None,final=False):
    with connect() as db,db.cursor() as c:
        c.execute('''SELECT o.id,o.topic_id,o.stamp,o.kind,o.payload,t.payload topic FROM paired_occurrence o
            JOIN article_semantic_topic t ON t.id=o.topic_id WHERE o.run_id=%s ORDER BY o.stamp''',(run_id,));occurrences=list(c.fetchall())
        c.execute('SELECT stamp,status,error,reused_from FROM article_checkpoint WHERE run_id=%s ORDER BY stamp',(run_id,));states=list(c.fetchall())
    result={k:v for k,v in base.items() if k!='checkpoints'};result['rows']=paired.build_rows(run_id,base,occurrences)
    stage_names(result,progress,final)
    result['progress']=dict(progress)
    result['observations']=[dict(stamp=s['stamp'],state='complete' if s['status']=='complete' else 'partial' if s['status']=='partial' else 'unknown',reused_from=s['reused_from'],error=s['error']) for s in states]
    with connect() as db,db.cursor() as c:c.execute('UPDATE paired_run SET summary=%s,status=%s WHERE id=%s',(json.dumps(result,ensure_ascii=False),progress['stage'],run_id))
    if hook:hook(result)
    return result


def prepare_article(context,progress_hook=None):
    ensure_disk_space();init();manifest=acquire_manifest(context);checkpoints=checkpoint_schedule(context,manifest);config=run_configuration(context,checkpoints);run_id=storage.digest(config)
    base=dict(topic=dict(id=context.topic,title=context.title,languages=list(context.languages)),run=run_id,version=VERSION,mode='historical',preparation_mode=context.mode,
        asOf=context.cutoff,bounds=[checkpoints[0]['stamp'],checkpoints[-1]['stamp']],checkpoints=[p['stamp'] for p in checkpoints],
        coverage=dict(sampling='Monthly as-of observations plus up to 20 recent changed-day checkpoints',anchors={a.lang:asdict(a) for a in context.anchors}),
        warning='Real sampled source revisions. Missing observations are unknown. Historical rendered HTML can contain newer transclusions. Model labels and question grouping require review.')
    with connect() as db,db.cursor() as c:
        c.execute('SELECT status,summary FROM paired_run WHERE id=%s',(run_id,));old=c.fetchone()
        if old and old['status']=='ready':
            result=json.loads(old['summary']);result['warning']=base['warning'];result['preparation_mode']=context.mode;stage_names(result,result['progress'],final=True)
            c.execute('UPDATE paired_run SET summary=%s WHERE id=%s',(json.dumps(result,ensure_ascii=False),run_id));return result
        c.execute("INSERT INTO paired_run(id,topic,version,status,configuration) VALUES(%s,%s,%s,'preparing',%s) ON DUPLICATE KEY UPDATE status='preparing',error=NULL",(run_id,context.topic,VERSION,json.dumps(config)))
        for point in checkpoints:c.execute('INSERT IGNORE INTO article_checkpoint(run_id,stamp,status,revision_tuple,error) VALUES(%s,%s,%s,%s,%s)',(run_id,point['stamp'],'unknown' if point['missing'] else 'pending',point['revision_tuple'],'Missing editions: '+','.join(point['missing']) if point['missing'] else None))
        c.execute('SELECT stamp,status,revision_tuple FROM article_checkpoint WHERE run_id=%s',(run_id,));states=list(c.fetchall())
    done={s['stamp'] for s in states if s['status']=='complete'};tuples={s['revision_tuple']:s['stamp'] for s in states if s['status']=='complete'}
    previous_progress=json.loads(old['summary']).get('progress',{}) if old and old.get('summary') else {}
    progress=dict(stage='matching',completed_checkpoints=len(done),total_checkpoints=len(checkpoints),workers=context.workers,
        **{k:v for k,v in previous_progress.items() if k.startswith('naming_')})
    publish(run_id,base,progress)
    from prepare import embedding_model
    with _model_lock:model=embedding_model(local_files_only=True)
    loader=lambda lang,rev:source_text(context,lang,rev)
    try:
        for point in reversed(checkpoints):
            stamp=point['stamp']
            if stamp in done or point['missing']:continue
            ensure_disk_space()
            previous=tuples.get(point['revision_tuple'])
            if previous:
                with connect() as db,db.cursor() as c:
                    c.execute('SELECT topic_id,pair_id,kind,payload FROM paired_occurrence WHERE run_id=%s AND stamp=%s',(run_id,previous));cached=list(c.fetchall())
                    for row in cached:c.execute('INSERT IGNORE INTO paired_occurrence VALUES(%s,%s,%s,%s,%s,%s,%s)',(storage.digest([run_id,row['topic_id'],stamp,row['pair_id']]),run_id,row['topic_id'],stamp,row['pair_id'],row['kind'],row['payload']))
                    c.execute("UPDATE article_checkpoint SET status='complete',reused_from=%s WHERE run_id=%s AND stamp=%s",(previous,run_id,stamp))
            else:
                print(context.topic,'checkpoint',stamp,flush=True)
                indexed={l:storage.index_revision(l,m,model,topic=context.topic,source_loader=loader) for l,m in point['revisions'].items()}
                nodes={l:paired.nodes(indexed[l],l,m,source_loader=loader) for l,m in point['revisions'].items()};pairs={}
                for la,lb in combinations(context.languages,2):
                    for edge in paired.symmetric_matches(indexed[la],indexed[lb],nodes[la],nodes[lb],namespace=VERSION+':'+context.topic,workers=context.workers):
                        # The existing verdict assesses only these exact texts; reuse it.
                        identity=storage.digest([paired.VERSION,la,edge['a'],lb,edge['b']]);pairs[identity]=dict(id=identity,a=nodes[la][edge['a']],b=nodes[lb][edge['b']],similarity=edge['similarity'])
                progress.update(stage='classifying',candidates_current=len(pairs));publish(run_id,base,progress)
                def assessment_error(error,batch):
                    progress['assessment_error']=safe_error(error)
                    progress['assessment_failed_pairs']=progress.get('assessment_failed_pairs',0)+len(batch)
                    print(context.topic,'assessment batch unavailable:',safe_error(error),flush=True)
                verdicts=paired.assess(pairs,workers=context.workers,allow_partial=True,on_error=assessment_error)
                progress['unassessed_current']=sum(v['kind']=='unassessed' for v in verdicts.values())
                assignments=assign_topics(context,pairs,verdicts);paired.store_occurrences(run_id,point,pairs,verdicts,assignments)
                progress['grouping_deferred_current']=sum(v['kind'] in ('contradiction','framing','coverage') for v in verdicts.values())-len(assignments)
                incomplete=any(v['kind']=='unassessed' for v in verdicts.values()) or progress['grouping_deferred_current']>0
                with connect() as db,db.cursor() as c:c.execute('UPDATE article_checkpoint SET status=%s WHERE run_id=%s AND stamp=%s',('partial' if incomplete else 'complete',run_id,stamp))
                if incomplete:
                    progress['stage']='partial';publish(run_id,base,progress,progress_hook);continue
                tuples[point['revision_tuple']]=stamp
            done.add(stamp);progress.update(stage='matching',completed_checkpoints=len(done));publish(run_id,base,progress,progress_hook)
        expected=sum(not p['missing'] for p in checkpoints);progress['stage']='ready' if len(done)==expected else 'partial'
        return publish(run_id,base,progress,progress_hook,final=True)
    except Exception as error:
        progress['stage']='partial';publish(run_id,base,progress,final=True)
        with connect() as db,db.cursor() as c:c.execute('UPDATE paired_run SET error=%s WHERE id=%s',(safe_error(error),run_id))
        raise


def corpus_catalog():
    with connect() as db,db.cursor() as c:
        c.execute("""SELECT wikidata_id topic,COUNT(DISTINCT lang) editions,GROUP_CONCAT(DISTINCT lang ORDER BY lang) languages,
            COALESCE(MAX(CASE WHEN lang='en' THEN title END),MIN(title)) title,SUM(CHAR_LENGTH(text)) prose_length
            FROM article WHERE wikidata_id REGEXP '^Q[0-9]+$' AND lang IN ('en','fi','sv')
            GROUP BY wikidata_id HAVING COUNT(DISTINCT lang)>=2 ORDER BY wikidata_id""");return list(c.fetchall())


def pilot_articles(rows=None,limit=10):
    rows=rows if rows is not None else corpus_catalog();by_id={r['topic']:r for r in rows};chosen=[]
    for identity in ('Q134949','Q2606233'):
        if identity in by_id:chosen.append(by_id[identity])
    groups=defaultdict(list)
    for row in rows:groups[row['languages']].append(row)
    for group in sorted(groups):
        available=sorted(groups[group],key=lambda r:(r['prose_length'],r['topic']))
        for fraction in (.2,.5,.8):
            if len(chosen)>=limit:break
            candidate=available[min(len(available)-1,int((len(available)-1)*fraction))]
            if candidate['topic'] not in {r['topic'] for r in chosen}:chosen.append(candidate)
    for row in sorted(rows,key=lambda r:(r['prose_length'],r['topic'])):
        if len(chosen)>=limit:break
        if row['topic'] not in {r['topic'] for r in chosen}:chosen.append(row)
    return chosen[:limit]


def showcase_articles(limit=20,prepared_only=False):
    """Read-only curated discovery, with actual local titles and prepared counts."""
    identities=[identity for identity,_ in SHOWCASE_ARTICLES];by_id={}
    with connect() as db,db.cursor() as c:
        c.execute('SELECT wikidata_id topic,lang,title FROM article WHERE wikidata_id IN ('+','.join(['%s']*len(identities))+') ORDER BY lang',identities)
        for row in c.fetchall():
            item=by_id.setdefault(row['topic'],dict(id=row['topic'],topic=row['topic'],title=row['title'],languages=[],featured=True,status='not_prepared',count=0,all_time_count=0,run=None))
            if row['lang'] in LANGUAGES and row['lang'] not in item['languages']:item['languages'].append(row['lang'])
            if row['lang']=='en':item['title']=row['title']
        c.execute("SELECT topic,id,status,summary FROM paired_run WHERE version=%s AND topic IN ("+','.join(['%s']*len(identities))+") AND summary IS NOT NULL ORDER BY (status='ready') DESC,updated DESC",[VERSION,*identities])
        seen=set()
        for row in c.fetchall():
            if row['topic'] in seen or row['topic'] not in by_id:continue
            data=json.loads(row['summary']);item=by_id[row['topic']];seen.add(row['topic'])
            latest={r['id'] for r in data['rows'] if any(p['start']==data['asOf'] for p in r['phases'])}
            item.update(status=row['status'],count=len(latest),all_time_count=len(data['rows']),run=row['id'],asOf=data['asOf'],
                        preparation_mode=data.get('preparation_mode','history' if len(data.get('observations',[]))>1 else 'snapshot'))
        try:
            c.execute('SELECT article,status,error FROM article_preparation_queue WHERE article IN ('+','.join(['%s']*len(identities))+') ORDER BY updated DESC',identities)
            queued=set()
            for job in c.fetchall():
                if job['article'] in queued or job['article'] not in by_id:continue
                queued.add(job['article']);item=by_id[job['article']];item['job_status']=job['status']
                if item['status']=='not_prepared':item['status']='preparing' if job['status']=='running' else job['status']
                if job['error']:item['preparation_error']=job['error']
        except Exception as error:
            if getattr(error,'args',[None])[0]!=1146:raise
    results=[by_id[identity] for identity in identities if identity in by_id and len(by_id[identity]['languages'])>=2]
    # Three-edition candidates first, preserving the curated order within each tier.
    results.sort(key=lambda item:len(item['languages'])<3)
    if prepared_only:results=[r for r in results if r['status']=='ready']
    return results[:max(0,min(20,limit))]


def enqueue(context,priority=100):
    init();configuration=context.configuration();identity=storage.digest(configuration)
    with connect() as db,db.cursor() as c:c.execute("INSERT IGNORE INTO article_preparation_queue(id,article,mode,configuration,status,priority) VALUES(%s,%s,%s,%s,'queued',%s)",(identity,context.topic,context.mode,json.dumps(configuration),priority))
    return identity


def _claim():
    with connect() as db,db.cursor() as c:
        db.begin();c.execute("SELECT id,configuration FROM article_preparation_queue WHERE status='queued' ORDER BY priority,id LIMIT 1 FOR UPDATE");row=c.fetchone()
        if row:c.execute("UPDATE article_preparation_queue SET status='running' WHERE id=%s",(row['id'],))
        db.commit();return row


def _run_job(job,hook=None):
    """A resumed queue entry cannot duplicate a still-running provider job."""
    name='article_job_'+job['id'][:48]
    with connect() as db,db.cursor() as c:
        c.execute('SELECT GET_LOCK(%s,0) locked',(name,))
        if c.fetchone()['locked']!=1:return dict(job=job['id'],status='running_elsewhere')
        try:return _run_job_locked(job,hook)
        finally:c.execute('SELECT RELEASE_LOCK(%s)',(name,))


def _run_job_locked(job,hook=None):
    raw=json.loads(job['configuration']);anchors=tuple(EditionAnchor(**a) for a in raw['anchors']);context=ArticleContext(raw['topic'],raw['title'],anchors,raw['mode'],raw['since'],min(2,raw.get('workers',2)))
    try:
        result=prepare_article(context,hook)
        with connect() as db,db.cursor() as c:c.execute('UPDATE article_preparation_queue SET status=%s,run_id=%s,error=NULL WHERE id=%s',(result['progress']['stage'],result['run'],job['id']))
        return dict(article=context.topic,run=result['run'],status=result['progress']['stage'],questions=len(result['rows']))
    except Exception as error:
        status='paused_disk' if isinstance(error,DiskGuardError) else 'failed'
        description=safe_error(error)
        with connect() as db,db.cursor() as c:c.execute('UPDATE article_preparation_queue SET status=%s,error=%s WHERE id=%s',(status,description[:100],job['id']))
        return dict(article=context.topic,status=status,error=description)


def work(workers=2,once=False,progress_hook=None):
    init();results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            jobs=[job for _ in range(workers) if (job:=_claim())]
            if not jobs:break
            paused=False
            for future in as_completed([pool.submit(_run_job,job,progress_hook) for job in jobs]):
                result=future.result();results.append(result);print(json.dumps(result),flush=True)
                paused=paused or result.get('status')=='paused_disk'
            if once or paused:break
    return results


def queue_status():
    with connect() as db,db.cursor() as c:c.execute('SELECT id,article,mode,status,run_id,error,updated FROM article_preparation_queue ORDER BY priority,id');return list(c.fetchall())


def resume_queue(topic):
    """Explicitly resume work, without resetting any provider reservations."""
    if not re.fullmatch(r'Q\d{1,15}',topic):raise ValueError('Choose an article to resume.')
    init()
    changed=0
    with connect() as db,db.cursor() as c:
        c.execute("SELECT id FROM article_preparation_queue WHERE article=%s AND status IN ('running','partial','failed','paused_disk','held_provider')",(topic,));rows=list(c.fetchall())
        for row in rows:
            name='article_job_'+row['id'][:48];c.execute('SELECT GET_LOCK(%s,0) locked',(name,))
            if c.fetchone()['locked']!=1:continue
            try:
                c.execute("UPDATE article_preparation_queue SET status='queued',error=NULL WHERE id=%s AND status IN ('running','partial','failed','paused_disk','held_provider')",(row['id'],));changed+=c.rowcount
            finally:c.execute('SELECT RELEASE_LOCK(%s)',(name,))
    return changed


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('catalog');pilot=sub.add_parser('pilot');pilot.add_argument('--limit',type=int,default=10)
    showcase=sub.add_parser('showcase');showcase.add_argument('--limit',type=int,default=20);showcase.add_argument('--prepared-only',action='store_true')
    queue=sub.add_parser('enqueue');queue.add_argument('--pilot',action='store_true');queue.add_argument('--showcase',action='store_true');queue.add_argument('--all',action='store_true');queue.add_argument('--mode',choices=['snapshot','history'],default='snapshot');queue.add_argument('--since',default='2020-01-01')
    prepare=sub.add_parser('prepare');prepare.add_argument('--topic',required=True);prepare.add_argument('--languages');prepare.add_argument('--mode',choices=['snapshot','history'],default='history');prepare.add_argument('--since',default='2020-01-01');prepare.add_argument('--workers',type=int,default=6)
    worker=sub.add_parser('worker');worker.add_argument('--workers',type=int,choices=[1,2],default=2);worker.add_argument('--once',action='store_true');sub.add_parser('status')
    resume=sub.add_parser('resume');resume.add_argument('--topic',required=True)
    args=parser.parse_args()
    if args.command=='catalog':print(json.dumps(corpus_catalog(),ensure_ascii=False,default=str))
    elif args.command=='pilot':print(json.dumps(pilot_articles(limit=args.limit),ensure_ascii=False,indent=2))
    elif args.command=='showcase':print(json.dumps(showcase_articles(args.limit,args.prepared_only),ensure_ascii=False,indent=2))
    elif args.command=='enqueue':
        if sum([args.pilot,args.showcase,args.all])!=1:parser.error('Choose exactly one of --pilot, --showcase or --all.')
        rows=showcase_articles() if args.showcase else pilot_articles() if args.pilot else corpus_catalog()
        for i,row in enumerate(rows):print(enqueue(article_context(row['topic'],mode=args.mode,since=args.since),i),row['topic'],flush=True)
    elif args.command=='prepare':
        result=prepare_article(article_context(args.topic,args.languages.split(',') if args.languages else None,args.mode,args.since,args.workers));print(json.dumps(dict(run=result['run'],questions=len(result['rows']),progress=result['progress'])))
    elif args.command=='worker':work(args.workers,args.once)
    elif args.command=='status':print(json.dumps(queue_status(),default=str,indent=2))
    elif args.command=='resume':print(resume_queue(args.topic))


if __name__=='__main__':main()

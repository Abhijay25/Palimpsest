"""Semantic zoom read model: unique period unions, never inferred lifetimes."""
from datetime import datetime,timezone
from urllib.parse import urlencode
from functools import lru_cache
import json
import calendar
import re

from skyline import KINDS,RANK,question_label


def parse_date(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (AttributeError,ValueError,TypeError):raise ValueError('Choose a valid historical period.') from None


def month_bounds(period):
    if not re.fullmatch(r'\d{4}-\d{2}',period or ''):raise ValueError('Choose a month in YYYY-MM format.')
    try:
        year,month=map(int,period.split('-'));start=datetime(year,month,1,tzinfo=timezone.utc)
        end=datetime(year+(month==12),1 if month==12 else month+1,1,tzinfo=timezone.utc)
    except ValueError:raise ValueError('Choose a valid month.') from None
    return start,end


def date_string(value):return value.isoformat().replace('+00:00','Z')


def observations(data):
    if 'observations' in data:return data['observations']
    state='complete' if data.get('progress',{}).get('stage')=='ready' else 'partial'
    return [dict(stamp=s,state=state) for s in sorted({p['start'] for r in data['rows'] for p in r['phases']})]


def latest_month(data):
    observed=[o['stamp'] for o in observations(data) if o.get('state') in ('complete','partial')]
    return max(observed or [data['asOf']])[:7]


def union_questions(data,languages,start,end,current='en',stamp=None):
    """Strongest actual selected pair, latest supporting date, reader language."""
    selected=set(languages);groups={}
    for row in data['rows']:
        for phase in row['phases']:
            if stamp and phase['start']!=stamp:continue
            observed=parse_date(phase['start'])
            if not start<=observed<end:continue
            for pair in phase.get('pairs',[]):
                langs={e['lang'] for e in pair['evidence']}
                if len(langs)<2 or not langs<=selected or pair['kind'] not in RANK:continue
                score=(RANK[pair['kind']],observed.timestamp(),current in langs)
                old=groups.get(row['id'])
                if old is None or score>old['_score'] or (score==old['_score'] and pair['id']<old['occurrence']):
                    left=current if current in langs else next(l for l in ('en','fi','sv') if l in langs)
                    groups[row['id']]=dict(id=row['id'],title=row['title'],kind=pair['kind'],stamp=phase['start'],
                        pair=' ↔ '.join([left.upper(),*sorted(l.upper() for l in langs if l!=left)]),
                        occurrence=pair['id'],left=left,_score=score)
    return list(groups.values())


def period_state(data,start,end):
    low,high=map(parse_date,data['bounds'])
    if end<=low or start>high:return 'unavailable'
    obs=[o for o in observations(data) if start<=parse_date(o['stamp'])<end]
    assessed=[o for o in obs if o.get('state') in ('complete','partial')]
    if not assessed:return 'unknown'
    return 'partial' if any(o.get('state')!='complete' for o in obs) else 'complete'


def filter_questions(data,languages,items,query,mode):
    if not query:return items,dict(mode='none',warning='')
    if not 2<=len(query)<=240:raise ValueError('Search with 2–240 characters.')
    if mode not in ('keyword','hybrid'):raise ValueError('Choose keyword or hybrid search.')
    from question_search import search
    result=search(data['topic']['id'],languages,[i['id'] for i in items],query,mode=mode)
    ranked={m['id']:m['relevance'] for m in result['matches']}
    return [dict(i,relevance=ranked[i['id']]) for i in items if i['id'] in ranked],result


@lru_cache(maxsize=64)
def source_titles(run,identities):
    """Fallback labels must come from this exact selected evidence, not a foreign representative."""
    if not identities:return {}
    from core import connect
    with connect() as db,db.cursor() as c:
        c.execute('SELECT id,payload FROM paired_occurrence WHERE run_id=%s AND id IN ('+','.join(['%s']*len(identities))+')',[run,*identities])
        return {r['id']:question_label(json.loads(r['payload'])) for r in c.fetchall()}


def periods(data,languages,level='year',year=None,query='',search_mode='keyword',current='en'):
    low,high=map(parse_date,data['bounds']);windows=[]
    if level=='year':
        for value in range(low.year,high.year+1):
            windows.append((str(value),datetime(value,1,1,tzinfo=timezone.utc),datetime(value+1,1,1,tzinfo=timezone.utc)))
    elif level=='month':
        try:year=int(year)
        except (ValueError,TypeError):raise ValueError('Choose a year for the monthly view.') from None
        if not 1<=year<9999:raise ValueError('Choose a valid year.')
        windows=[(f'{year:04d}-{month:02d}',*month_bounds(f'{year:04d}-{month:02d}')) for month in range(1,13)]
    else:raise ValueError('Choose year or month overview.')
    # Search only within this view before top-K semantic retrieval.
    all_items=union_questions(data,languages,windows[0][1],windows[-1][2],current)
    matched,search_result=filter_questions(data,languages,all_items,query,search_mode)
    ids={i['id'] for i in matched};output=[]
    for key,start,end in windows:
        items=[i for i in union_questions(data,languages,start,end,current) if i['id'] in ids]
        counts={k:sum(i['kind']==k for i in items) for k in KINDS}
        output.append(dict(key=key,start=date_string(start),end=date_string(end),state=period_state(data,start,end),counts=counts,total=len(items)))
    return dict(topic=data['topic'],run=data['run'],bounds=data['bounds'],asOf=data['asOf'],level=level,
        periods=output,latest_month=latest_month(data),mode=search_result['mode'],warning=search_result.get('warning',''),filtered=bool(query),
        progress=data.get('progress',{}))


def constellation(data,languages,period=None,stamp=None,page=1,current='en',query='',search_mode='keyword',back=''):
    period=period or latest_month(data);start,end=month_bounds(period)
    dates=[o for o in observations(data) if start<=parse_date(o['stamp'])<end]
    if stamp and stamp not in {o['stamp'] for o in dates if o.get('state') in ('complete','partial')}:
        raise ValueError('Choose an assessed observation in this month.')
    items=union_questions(data,languages,start,end,current,stamp)
    items,search_result=filter_questions(data,languages,items,query,search_mode)
    items.sort(key=lambda i:(-i.get('relevance',0),-RANK[i['kind']],i['id']))
    pages=max(1,(len(items)+99)//100)
    if not 1<=page<=pages:raise ValueError('That question page is unavailable.')
    from question_titles import labels
    page_items=items[(page-1)*100:page*100]
    titles=labels(data['topic']['id'],[i['id'] for i in page_items])
    fallback=source_titles(data['run'],tuple(sorted(i['occurrence'] for i in page_items if titles.get(i['id'],{}).get('status')!='accepted')))
    if len(back)>2500:raise ValueError('Invalid explorer return context.')
    if not back:
        values=[('topic',data['topic']['id']),('run',data['run']),('view','questions'),('period',period),('q',query)]
        values.extend(('languages',l) for l in languages);back=urlencode(values)
    out=[]
    for item in page_items:
        title=titles.get(item['id'],{});accepted=title.get('status')=='accepted'
        q=[('lang',item['left']),('run',data['run']),('group',item['id']),('stamp',item['stamp']),('occurrence',item['occurrence']),('skyline',back)]
        q.extend(('languages',l) for l in languages)
        out.append(dict(id=item['id'],title=title.get('title') if accepted else fallback.get(item['occurrence'],item['title']),kind=item['kind'],pair=item['pair'],stamp=item['stamp'],
            title_status=title.get('status','provisional'),href='/langcompare/'+data['topic']['id']+'?'+urlencode(q)))
    return dict(topic=data['topic'],run=data['run'],bounds=data['bounds'],asOf=data['asOf'],period=period,latest_month=latest_month(data),
        questions=out,total=len(items),page=page,pages=pages,observations=dates,state=period_state(data,start,end),
        counts={k:sum(i['kind']==k for i in items) for k in KINDS},mode=search_result['mode'],warning=search_result.get('warning',''),filtered=bool(query),progress=data.get('progress',{}))


def article_lookup(query=''):
    from core import connect
    query=query.strip()[:150]
    with connect() as db,db.cursor() as c:
        c.execute('''SELECT a.wikidata_id id,COALESCE(MAX(CASE WHEN a.lang='en' THEN a.title END),MAX(a.title)) title,
          GROUP_CONCAT(DISTINCT a.lang ORDER BY a.lang) langs,
          EXISTS(SELECT 1 FROM paired_run r WHERE r.topic=a.wikidata_id AND r.summary IS NOT NULL) prepared
          FROM article a WHERE a.wikidata_id REGEXP '^Q[0-9]+$' AND (%s='' OR a.wikidata_id=%s OR a.wikidata_id IN
          (SELECT wikidata_id FROM article WHERE title LIKE %s)) GROUP BY a.wikidata_id HAVING COUNT(DISTINCT a.lang)>=2
          ORDER BY prepared DESC,title LIMIT 30''',(query,query,'%'+query+'%'))
        rows=c.fetchall()
    return dict(articles=[dict(id=r['id'],title=r['title'],languages=r['langs'].split(','),prepared=bool(r['prepared'])) for r in rows])

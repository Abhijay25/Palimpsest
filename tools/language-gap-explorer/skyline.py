"""Pure skyline aggregation and cached historical tracker handoff."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
from urllib.parse import urlencode

KINDS=('coverage','framing','contradiction')
RANK={kind:i for i,kind in enumerate(KINDS)}
LABELS={'coverage':'Additional context','framing':'Different framing','contradiction':'Possible contradiction'}
QUESTIONS={'dates':'When did this happen?','cause':'What caused this event?','actors':'Who was involved or responsible?',
           'outcome':'What was the outcome?','scale':'What was the scale?','framing':'How is the event characterized?',
           'coverage':'Which information is included?','account':'Which account of events is given?'}
NAMES={'en':'English','fi':'Suomi','sv':'Svenska'}


def selection(args):
    topic=args.get('topic','Q134949');languages=list(dict.fromkeys(args.getlist('languages') or ['en','fi','sv']))
    run=args.get('run')
    if not re.fullmatch(r'Q\d{1,15}',topic) or not 2<=len(languages)<=3 or not set(languages)<=NAMES.keys():
        raise ValueError('Choose an article and two or three supported editions.')
    if run and not re.fullmatch(r'[a-f0-9]{64}',run):raise ValueError('Invalid comparison run.')
    return topic,languages,run


def phases_at(data,stamp,languages):
    """One question once; category derives only from actual selected pairs."""
    out={};selected=set(languages)
    for row in data['rows']:
        for phase in row['phases']:
            if phase['start']!=stamp:continue
            pairs=[p for p in phase.get('pairs',[]) if len({e['lang'] for e in p['evidence']})>=2 and {e['lang'] for e in p['evidence']}<=selected]
            if not pairs:continue
            kind=max((p['kind'] for p in pairs if p['kind'] in RANK),key=RANK.get,default=None)
            if kind and (row['id'] not in out or RANK[kind]>RANK[out[row['id']][2]]):out[row['id']]=(row,phase,kind)
    return list(out.values())


def aggregate(data,languages):
    observations=data.get('observations') or [dict(stamp=s,state='complete' if data.get('progress',{}).get('stage')=='ready' else 'partial')
        for s in sorted({p['start'] for row in data['rows'] for p in row['phases']})]
    result=[]
    for observation in observations:
        counts={kind:0 for kind in KINDS}
        for _,_,kind in phases_at(data,observation['stamp'],languages):counts[kind]+=1
        result.append(dict(**observation,counts=counts,total=sum(counts.values())))
    return dict(topic=data['topic'],run=data['run'],bounds=data['bounds'],asOf=data['asOf'],observations=result,
                progress=data.get('progress',{}),warning=data.get('warning',''),languages=languages,
                distinct_questions=len({row['id'] for row in data['rows']}))


def occurrence_choice(occurrences,languages,current='en',kind=None,identity=None):
    selected=set(languages)
    eligible=[o for o in occurrences if len({e['lang'] for e in o['evidence']})>=2 and {e['lang'] for e in o['evidence']}<=selected]
    if identity:return next((o for o in eligible if o['id']==identity),None)
    eligible.sort(key=lambda o:(o['kind']!=kind,-RANK.get(o['kind'],-1),not any(e['lang']==current for e in o['evidence']),o['id']))
    return eligible[0] if eligible else None


def left_language(occurrence,current):
    available={e['lang'] for e in occurrence['evidence']}
    return current if current in available else next(l for l in ('en','fi','sv') if l in available)


def question_label(occurrence):
    evidence=occurrence['evidence']
    meaningful=[e for e in evidence if e.get('section') not in ('','Introduction')]
    chosen=next((e for e in meaningful if e['lang']=='en'),meaningful[0] if meaningful else evidence[0])
    section=chosen.get('section','Selected evidence')
    if section=='Introduction':section='Opening account'
    return section+' · '+QUESTIONS.get(occurrence.get('question'),QUESTIONS['account'])


def question_page(data,languages,stamp,page=1,kind='all',current='en',back_query=''):
    from paired_history import detail
    if stamp not in {o['stamp'] for o in data.get('observations',[])}:raise ValueError('Choose a stored observation.')
    if kind!='all' and kind not in KINDS:raise ValueError('Unknown difference category.')
    items=[item for item in phases_at(data,stamp,languages) if kind=='all' or item[2]==kind]
    items.sort(key=lambda item:(-RANK[item[2]],item[0]['id']))
    pages=max(1,(len(items)+9)//10)
    if not 1<=page<=pages:raise ValueError('That question page is unavailable.')
    def present(item):
        row,phase,category=item;stored=detail(data['run'],row['id'],stamp,languages=languages)
        if not stored:return dict(id=row['id'],title=row['title'],kind=category,unavailable=True)
        occurrence=occurrence_choice(stored['occurrences'],languages,current,category)
        if not occurrence:return dict(id=row['id'],title=row['title'],kind=category,unavailable=True)
        left=left_language(occurrence,current);others=sorted({e['lang'] for e in occurrence['evidence']} - {left})
        query=[('lang',left),('run',data['run']),('group',row['id']),('stamp',stamp),('occurrence',occurrence['id']),('skyline',back_query)]
        query += [('languages',lang) for lang in languages]
        pairs=sorted({' ↔ '.join(sorted({e['lang'].upper() for e in p['evidence']})) for p in phase['pairs'] if {e['lang'] for e in p['evidence']}<=set(languages)})
        handoff='/article/'+data['topic']['id']+'?'+urlencode(query)
        return dict(id=row['id'],title=question_label(occurrence),kind=category,label=LABELS[category],pairs=pairs,
                    occurrences=len(stored['occurrences']),destination=' ↔ '.join([left.upper()]+[l.upper() for l in others]),
                    href='/langcompare/'+data['topic']['id']+'?'+urlencode(query),article_href=handoff+'&tab=language',
                    flags_href=handoff+'&tab=flags&scan=1')
    with ThreadPoolExecutor(max_workers=4) as pool:questions=list(pool.map(present,items[(page-1)*10:page*10]))
    return dict(questions=questions,total=len(items),page=page,pages=pages,stamp=stamp)


def tracker_context(topic,args):
    from paired_history import summary,detail
    from review_view import highlight_source
    requested,languages,run=selection(args)
    if requested!=topic or not run:raise ValueError('The historical article/run context is incomplete.')
    group=args.get('group','');stamp=args.get('stamp','')
    if not re.fullmatch(r'[a-f0-9]{64}',group):raise ValueError('Invalid semantic question.')
    data=summary(topic,languages,run=run)
    if not data:raise LookupError('This historical comparison is unavailable. The tracker has not switched to snapshot results.')
    matching=next((item for item in phases_at(data,stamp,languages) if item[0]['id']==group),None)
    if not matching:raise LookupError('The selected question was not observed for these editions at this checkpoint.')
    row,phase,kind=matching;stored=detail(run,group,stamp,languages=languages)
    if not stored:raise LookupError('Stored historical source occurrences are unavailable.')
    occurrence=occurrence_choice(stored['occurrences'],languages,args.get('lang','en'),kind,args.get('occurrence'))
    if not occurrence:raise LookupError('That source occurrence does not belong to this historical selection.')
    current=left_language(occurrence,args.get('lang','en'))
    evidence=[]
    for source in occurrence['evidence']:
        if source.get('stamp','')>stamp or source.get('url')!=f"https://{source['lang']}.wikipedia.org/w/index.php?oldid={source['revision']}":
            raise LookupError('Stored source revision context is inconsistent with this observation.')
        item=dict(source);item['rev_id']=source['revision'];item['quote_html']=highlight_source(source['quote'],source.get('highlights',[]));evidence.append(item)
    back=args.get('skyline','')
    # The return target is always our own explorer, never a supplied URL.
    if len(back)>2500:raise ValueError('Invalid skyline return context.')
    from question_titles import labels
    generated=labels(topic,[group]).get(group,{})
    return dict(historical=True,topic=topic,title=data['topic']['title'],current_lang=current,source=current,
                selected_languages=languages,langs=list(NAMES),historical_run=run,historical_group=group,
                historical_stamp=stamp,historical_date=datetime.fromisoformat(stamp.replace('Z','+00:00')).strftime('%d %b %Y'),
                historical_title=generated['title'] if generated.get('status')=='accepted' else question_label(occurrence),historical_label=LABELS[occurrence['kind']],
                historical_evidence=evidence,historical_occurrences=stored['occurrences'],historical_occurrence=occurrence['id'],
                historical_reason=phase['reason'],historical_action=phase['action'],historical_back='/explore'+('?' + back if back else ''),
                historical_sampled=phase.get('sampled',False),demo=False)

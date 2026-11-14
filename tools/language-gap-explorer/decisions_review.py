"""Batched Decisions-only review. All UI prose is a template, all quotes are source text."""
import json,re
from core import connect
from live_api import decisions

def sentences(passages):
    result={}
    for p in passages:
        for i,m in enumerate(re.finditer(r'[^\n.!?]+(?:[.!?]+|$)',p['text'])):
            quote=m.group().strip()
            if len(quote)>20:
                result[f'{p["id"][:12]}s{i}']={'passage':p,'quote':quote}
            if i>=11: break
    if not result and passages:
        p=passages[0]
        result[p['id'][:12]+'context']={'passage':p,'quote':p['text']}
    return result

def process_batch(groups,articles):
    from pipeline import POLICY,digest
    from mock_review import CATEGORIES
    requests=[]; questions=[]; tasks=[]
    for gi,group in enumerate(groups):
        pp=json.loads(group['payload']); anchor=next(p for p in pp if p['id']==group['anchor_id'])
        for lang in articles:
            if lang==anchor['lang']: continue
            target=[p for p in pp if p['lang']==lang]
            if not target: continue
            name=f'g{gi}_{lang}'
            source_sentences=sentences([anchor]); target_sentences=sentences(target)
            # Keep choices bounded and deterministic; full passages still supply context.
            source_sentences=dict(list(source_sentences.items())[:12])
            target_sentences=dict(list(target_sentences.items())[:24])
            requests.append({'id':name,'source':anchor,'target_language':lang,'target_passages':target})
            instructions=POLICY+f' Evaluate ONLY comparison {name}. Compare the source against the target passages. Do not confuse different legal milestones or time periods. A low similarity is not a contradiction.'
            questions += [{'type':'choice','name':name+'_relation','instructions':instructions,
              'choices':[{'value':v,'description':d} for v,d in {
                'conflict':'Explicit incompatible assertions about the SAME event, time and scope.',
                'same':'The main factual content is compatible or equivalent.',
                'coverage':'Different coverage or added detail without an explicit contradiction.',
                'uncertain':'Insufficient evidence or ambiguity; no conflict established.'}.items()]},
              {'type':'predicate','name':name+'_conflict','instructions':instructions+' Is there an explicit factual contradiction about the SAME event, time and scope? Different years for adoption versus entry into force are not a contradiction.'}]
            for side,options in [('source',source_sentences),('target',target_sentences)]:
                questions.append({'type':'choice','name':name+'_'+side,
                  'instructions':instructions+f' Select the {side} sentence most relevant to a possible contradiction. Select none if no relevant sentence exists.',
                  'choices':[{'value':'none','description':'No relevant contradictory sentence.'}]+[
                    {'value':k,'description':e['quote'][:1800]} for k,e in options.items()]})
            tasks.append((group,name,anchor,lang,source_sentences,target_sentences))
    answers=decisions(requests,questions) if questions else {}
    grouped={g['id']:[] for g in groups}; group_judgments={g['id']:{} for g in groups}
    for group,name,anchor,lang,source_options,target_options in tasks:
        relation=answers[name+'_relation']; score=answers[name+'_conflict']['probability']
        # Warning colors are reserved for a corroborated decision with exact source evidence.
        category=relation['choice']
        source=source_options.get(answers[name+'_source']['choice'])
        target=target_options.get(answers[name+'_target']['choice'])
        if category=='conflict' and (score<.8 or not source or not target): category='uncertain'
        if relation.get('confidence',0)<.5: category='uncertain'
        # Non-conflicts have no claimed contradictory span. Show source context unmarked.
        source=source or {'passage':anchor,'quote':anchor['text']}
        target=target or next(iter(target_options.values()),None)
        if target is None: continue
        evidence=[]
        for chosen in (source,target):
            p=chosen['passage']; a=articles[p['lang']]; quote=chosen['quote']
            start=a['text'].find(quote,p['start_offset'])
            if start<0: raise ValueError('Selected sentence is not in source revision.')
            evidence.append(dict(lang=p['lang'],title=a['title'],quote=quote,translation='',
              highlight=quote if category=='conflict' else '',section=p['heading'],rev_id=a['rev_id'],
              start=start,end=start+len(quote),url=f'https://{p["lang"]}.wikipedia.org/w/index.php?oldid={a["rev_id"]}'))
        templates={
          'conflict':('Possible factual conflict','Decisions identified potentially incompatible statements about the same subject. Read the highlighted source sentences together.'),
          'same':('Compatible information','No factual contradiction was identified in this comparison.'),
          'coverage':('Different coverage','These passages discuss different details. This does not establish a factual error or article-wide omission.'),
          'uncertain':('No clear conflict established','The evidence was not strong enough to mark a factual conflict. Additional context may resolve the difference.')}
        title,summary=templates[category]
        finding={'id':digest([group['id'],name,'decisions-only']),'category':category,'label':CATEGORIES[category],
          'title':title,'summary':summary,'reasoning':f'Template explanation: the conflict predicate scored {score:.2f}; highlighting requires a conflict classification, a score of at least 0.80, and selected source sentences. This score is not verified accuracy.',
          'action':'Check the selected source revisions and their cited sources before proposing an edit.',
          'note':'Review these statements for event, date and scope differences. Do not change either edition without checking the sources.',
          'evidence':evidence,'mode':'live','engine':'decisions-only','decision':relation,'conflict_probability':score}
        grouped[group['id']].append(finding)
        group_judgments[group['id']][name]={k:answers[name+'_'+k] for k in ('relation','conflict','source','target')}
    with connect() as db,db.cursor() as c:
        for group in groups:
            c.execute("UPDATE review_group SET status='done',judgments=%s,findings=%s WHERE id=%s",
              (json.dumps(group_judgments[group['id']]),json.dumps(grouped[group['id']]),group['id']))

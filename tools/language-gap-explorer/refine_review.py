"""Focused follow-up only for high discrepancy predicates. No text generation."""
import argparse,json,re
from core import connect
from live_api import decisions
from decisions_review import sentences
from pipeline import VERSION,digest,articles

def refine(topic):
    aa=articles(topic)
    with connect() as db,db.cursor() as c:
        c.execute('SELECT id FROM review_run WHERE topic=%s AND version=%s ORDER BY created DESC LIMIT 1',(topic,VERSION)); run=c.fetchone()
        if not run: return
        c.execute("SELECT * FROM review_group WHERE run_id=%s AND status='done'",(run['id'],)); groups=c.fetchall()
    total=0
    for group in groups:
        payload=json.loads(group['payload']); anchor=next(p for p in payload if p['id']==group['anchor_id'])
        verdicts=json.loads(group['judgments']); findings=json.loads(group['findings'])
        for name,j in verdicts.items():
            if j.get('conflict',{}).get('probability',0)<.8: continue
            focused_id=digest([group['id'],name,'focused-v1'])
            findings=[f for f in findings if f['id']!=focused_id]
            lang=name.split('_')[-1]
            options={'source':dict(list(sentences([anchor]).items())[:12]),
                'target':dict(list(sentences([p for p in payload if p['lang']==lang]).items())[:24])}
            questions=[]
            for side,ss in options.items():
                questions.append({'type':'choice','name':side,'instructions':f'Choose the {side} sentence carrying the factual difference suggested by this comparison. Select even if the difference could be reconciled as different legal milestones. Do not select none merely because context might resolve it.',
                    'choices':[{'value':'none','description':'No sentence discusses the same subject or a factual difference.'}]+[{'value':k,'description':v['quote']} for k,v in ss.items()]})
            selected=decisions({'anchor':anchor,'target':[p for p in payload if p['lang']==lang],'previous_discrepancy_score':j['conflict']['probability']},questions)
            pair=[options[side].get(selected[side]['choice']) for side in ('source','target')]
            if any(p is None for p in pair): continue
            quotes=[p['quote'] for p in pair]
            focused=decisions({'source':quotes[0],'target':quotes[1]},[{
                'type':'predicate','name':'needs_review','instructions':'Do these sentences state different factual values, dates, statuses or scopes about the same subject that an editor should reconcile or clarify? Different legal milestones can warrant clarification even if both dates are true. Ignore mere wording differences. This is a discrepancy-review question, not a claim that either statement is false.'},{
                'type':'choice','name':'relationship','instructions':'What best describes these two sentences?',
                'choices':[{'value':k,'description':d} for k,d in {
                    'different_values':'Different values for apparently the same fact.',
                    'different_milestones':'Possibly different milestones, legal statuses or scopes.',
                    'compatible':'Same information or complementary facts, no discrepancy apparent.',
                    'unrelated':'Different subjects.', 'uncertain':'Cannot resolve the relationship from these excerpts.'}.items()]},{
                'type':'predicate','name':'same_claim','instructions':'Do these sentences assert the same substantive factual claim, allowing translation and harmless paraphrasing? Different factual dates or distinct legal statuses are not the same claim. Shared words alone do not establish equivalence.'}])
            if focused['needs_review']['probability']<.8 or focused['same_claim']['probability']>=.8 or focused['relationship']['choice'] in ('compatible','unrelated'): continue
            tokens=[list(re.finditer(r"\w+(?:[-’']\w+)*",q))[:100] for q in quotes]
            word_questions=[{'type':'predicate','name':f's{s}w{i}',
                'instructions':f'For sentence {s}, is token {i} ({m.group()}) part of the specific factual difference to inspect (date, quantity, status, negation or critical qualifier)? Exclude shared generic words, articles, conjunctions and ordinary reporting verbs. Judge its role in this pair, not whether it is true.'}
                for s,tt in enumerate(tokens) for i,m in enumerate(tt)]
            word_scores=decisions({'sentences':quotes,'token_lists':[[m.group() for m in tt] for tt in tokens]},word_questions,allow_refusals=True)
            entries=[]
            for side,choice in enumerate(pair):
                p=choice['passage'];a=aa[p['lang']]; quote=choice['quote'];start=a['text'].find(quote,p['start_offset'])
                if start<0: raise ValueError('Focused evidence no longer matches source.')
                spans=[{'start':m.start(),'end':m.end()} for i,m in enumerate(tokens[side]) if word_scores[f's{side}w{i}'].get('probability',0)>=.8]
                entries.append(dict(lang=p['lang'],title=a['title'],quote=quote,section=p['heading'],translation='',highlight='',highlights=spans,
                    rev_id=a['rev_id'],start=start,end=start+len(quote),url=f'https://{p["lang"]}.wikipedia.org/w/index.php?oldid={a["rev_id"]}'))
            numbers=[re.findall(r'\b\d{3,4}\b',q) for q in quotes]
            title=(' / '.join(numbers[0][:3])+' vs '+' / '.join(numbers[1][:3])) if all(numbers) and numbers[0]!=numbers[1] else 'Factual difference to reconcile'
            new=dict(id=digest([group['id'],name,'focused-v1']),category='conflict',label='Possible factual discrepancy',title=title,
                summary='These excerpts contain a factual difference that may need clarification; both statements may still be valid.',
                reasoning=f'Focused discrepancy score: {focused["needs_review"]["probability"]:.2f}. Relationship: {focused["relationship"]["choice"]}. The separate questions are not a proof of factual error.',
                action='Check the event, legal milestone and source citations. Clarify scope rather than automatically replacing a date.',
                note='Reconcile the highlighted values and terminology against cited sources before editing.',evidence=entries,mode='live',engine='decisions-only-focused',decision=focused,conflict_probability=j['conflict']['probability'])
            # Replace the broad packet for this anchor/language pair, retaining raw judgments.
            old_id=digest([group['id'],name,'decisions-only'])
            findings=[f for f in findings if f['id'] not in (old_id,new['id'])]+[new];total+=1
        with connect() as db,db.cursor() as c:c.execute('UPDATE review_group SET findings=%s WHERE id=%s',(json.dumps(findings),group['id']))
    print('Focused discrepancy packets:',total,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('topic');refine(p.parse_args().topic)

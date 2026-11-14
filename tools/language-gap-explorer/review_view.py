"""Reader-facing selection and section grouping of existing review results."""
import re
from markupsafe import Markup,escape

def highlight_source(quote,spans):
    cursor=0;parts=[]
    for span in sorted(spans,key=lambda s:s['start']):
        start,end=span['start'],span['end']
        if not isinstance(start,int) or not isinstance(end,int) or not cursor<=start<end<=len(quote): continue
        parts.extend([escape(quote[cursor:start]),Markup('<mark>'),escape(quote[start:end]),Markup('</mark>')]);cursor=end
    parts.append(escape(quote[cursor:]));return Markup('').join(parts)

def select_languages(values,available,source,target):
    chosen=list(dict.fromkeys(values or [source,target]))
    if not 2<=len(chosen)<=3 or any(l not in available for l in chosen):
        raise ValueError('Choose two or three available language editions.')
    return chosen

def section_groups(findings,chosen):
    selected=set(chosen)
    filtered=[f for f in findings if len({e['lang'] for e in f['evidence']})>=2
        and {e['lang'] for e in f['evidence']}.issubset(selected)]
    # Merge only exact shared highlighted evidence, retaining every model judgment.
    merged=[]
    for finding in filtered:
        keys={(e['lang'],e['quote'],tuple((x['start'],x['end']) for x in e.get('highlights',[]))) for e in finding['evidence'] if e.get('highlights')}
        match=next((f for f,k in merged if finding['category']=='conflict' and f['category']=='conflict' and keys & k),None)
        if match is None:merged.append((dict(finding,evidence=list(finding['evidence']),supporting_judgments=[finding['id']]),keys))
        else:
            match['supporting_judgments'].append(finding['id'])
            existing={(e['lang'],e['quote']) for e in match['evidence']}
            match['evidence'].extend(e for e in finding['evidence'] if (e['lang'],e['quote']) not in existing)
    filtered=[f for f,k in merged]
    groups={}
    for f in filtered:
        for e in f['evidence']:
            if e.get('highlights') and f['category']=='conflict': e['quote_html']=highlight_source(e['quote'],e['highlights'])
        evidence=f['evidence']
        numbers=[]
        for e in evidence[:2]:
            selected_text=' '.join(e['quote'][s['start']:s['end']] for s in e.get('highlights',[]))
            selected_text=selected_text or (e.get('highlight') if e.get('highlight')!=e['quote'] else '') or e['quote']
            numbers.append(list(dict.fromkeys(re.findall(r'\b\d{3,4}\b',selected_text))))
        if len(numbers)==2 and numbers[0] and numbers[1] and numbers[0]!=numbers[1]:
            f['display_title']=' / '.join(numbers[0][:3])+' vs '+ ' / '.join(numbers[1][:3])
        else:
            text=f.get('claim') or (evidence[0]['quote'] if evidence else f['title'])
            words=text.split();f['display_title']=' '.join(words[:16])+('…' if len(words)>16 else '')
        # Use an English section label when available, without inventing translated
        # alignments between sections. This groups navigation, not factual claims.
        en=[e for e in f['evidence'] if e['lang']=='en']
        entry=(en or f['evidence'])[0]
        label=entry.get('section') or 'Introduction'
        if label==entry.get('title'): label='Introduction'
        key=(entry['lang'],label)
        group=groups.setdefault(key,{'title':label,'label_lang':entry['lang'],'findings':[],'languages':set()})
        group['findings'].append(f)
        group['languages'].update(e['lang'] for e in f['evidence'])
    order={'conflict':0,'coverage':1,'framing':2,'uncertain':3}
    result=list(groups.values())
    for i,g in enumerate(result):
        g['id']='review-section-'+str(i)
        g['languages']=sorted(g['languages'])
        g['actionable']=sum(f['category']!='uncertain' for f in g['findings'])
        g['uncertain']=len(g['findings'])-g['actionable']
        g['has_conflict']=any(f['category']=='conflict' for f in g['findings'])
    result.sort(key=lambda g:(not g['has_conflict'],g['actionable']==0,g['title'].casefold()))
    return filtered,result

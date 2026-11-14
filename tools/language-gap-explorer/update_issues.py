"""Edition-specific issue triage. Heuristics select reviews, not semantic verdicts."""
import difflib,re
from markupsafe import Markup,escape
LANG_NAMES={'en':'English','fi':'Finnish','sv':'Swedish'}
NEGATIONS={'en':{'not','no','never','without'},'fi':{'ei','eivät','ilman'},'sv':{'inte','ej','aldrig','utan'}}
def tokens(text):return re.findall(r'\w+',text.casefold())
def criteria(change,lang):
    old,new=tokens(change['before']),tokens(change['after'])
    if old==new:return []
    reasons=[]
    numbers=lambda words:[w for w in words if any(c.isdigit() for c in w)]
    if numbers(old)!=numbers(new):reasons.append('Dates or quantities changed')
    neg=NEGATIONS.get(lang,set())
    if (set(old)&neg)!=(set(new)&neg):reasons.append('Negation changed')
    changed=sum(max(b-a,y-x) for tag,a,b,x,y in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes() if tag!='equal')
    if changed>=12 and changed/max(len(old),len(new),1)>=.2:reasons.append('Substantial wording change')
    return reasons

def issue_items(rows,target):
    result=[]
    for row in rows:
        if row['kind']!='prose':continue
        foreign=row['lang']!=target;selected=[]
        for change in row['data']['changes']:
            reasons=criteria(change,row['lang'])
            side=next((s for s in change['counterparts'] if s['lang']==target),None)
            if foreign:
                old,new=tokens(change['before']),tokens(change['after'])
                delta=sum(max(b-a,y-x) for tag,a,b,x,y in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes() if tag!='equal')
                if not side or old==new or (not reasons and delta<3):continue
                reasons=reasons or ['Wording changed in a related passage']
            elif not reasons:continue
            selected.append(dict(change,reasons=reasons,counterparts=[side] if foreign else []))
        if not selected:continue
        reasons=list(dict.fromkeys(r for d in selected for r in d['reasons']))
        first=next((d for d in selected if 'Dates or quantities changed' in d['reasons']),selected[0]);removed=[];added=[]
        for tag,a,b,x,y in difflib.SequenceMatcher(None,tokens(first['before']),tokens(first['after']),autojunk=False).get_opcodes():
            if tag!='equal':
                removed.extend(w for w in tokens(first['before'])[a:b] if w.isdigit())
                added.extend(w for w in tokens(first['after'])[x:y] if w.isdigit())
        if removed and added:title=' / '.join(removed[:3])+' → '+' / '.join(added[:3])
        elif removed:title='Removed values: '+' / '.join(removed[:3])
        elif added:title='Added values: '+' / '.join(added[:3])
        else:
            text=first['after'] or first['before']
            title=' '.join(text.split()[:12])+('?' if len(text.split())>12 else '')
        title+=(' in '+LANG_NAMES[row['lang']])
        result.append(dict(row,issue_title=title,issue_type='cross' if foreign else 'local',reasons=reasons,changes=selected,target=target))
    return result

def compact_diff(before,after):
    old=re.findall(r'\s+|\S+',before);new=re.findall(r'\s+|\S+',after);parts=[]
    operations=difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes()
    for i,(tag,a,b,x,y) in enumerate(operations):
        if tag=='equal':
            words=new[x:y]
            if len(words)>48:
                if i==0:parts.extend([Markup('<span class="diff-ellipsis">… </span>'),escape(''.join(words[-24:]))])
                elif i==len(operations)-1:parts.extend([escape(''.join(words[:24])),Markup('<span class="diff-ellipsis"> …</span>')])
                else:parts.extend([escape(''.join(words[:24])),Markup('<span class="diff-ellipsis"> … </span>'),escape(''.join(words[-24:]))])
            else:parts.append(escape(''.join(words)))
        else:
            if tag in ('delete','replace'):parts.extend([Markup('<del>'),escape(''.join(old[a:b])),Markup('</del>')])
            if tag in ('insert','replace'):parts.extend([Markup('<ins>'),escape(''.join(new[x:y])),Markup('</ins>')])
    return Markup('').join(parts)

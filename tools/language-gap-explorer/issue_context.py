"""Source-bound issue explanations and explicit cached local translation.

Reads never generate prose, translate, prepare models, or call a paid provider.
Optional prepared explanations are content-addressed and preserve observations.
"""
import hashlib
import json
from pathlib import Path
import re
from core import ROOT

VERSION='issue-context-v1'

def source_key(source):
    return hashlib.sha256((source['lang']+'\0'+source['quote']).encode()).hexdigest()

def paragraphs(source):
    """Exact source paragraph slices, with no generated or rewritten original."""
    quote=source['quote'];start=0;result=[]
    for boundary in re.finditer(r'\n\s*\n',quote):
        if quote[start:boundary.start()].strip():result.append(dict(source,quote=quote[start:boundary.start()],paragraph_start=start,paragraph_end=boundary.start()))
        start=boundary.end()
    if quote[start:].strip():result.append(dict(source,quote=quote[start:],paragraph_start=start,paragraph_end=len(quote)))
    return result

def scope_key(kind,evidence):
    body=json.dumps([VERSION,kind,sorted((e['lang'],e['quote'],e.get('section',''),str(e.get('revision',e.get('rev_id',''))),e.get('start'),e.get('end')) for e in evidence)],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(body.encode()).hexdigest()

def explanation_path(kind,evidence):
    return ROOT/'data'/'issue-explanations'/(scope_key(kind,evidence)+'.json')

def first_statement(text,limit=270):
    text=re.split(r'(?<=[.!?])\s+',text.strip(),maxsplit=1)[0]
    return text if len(text)<=limit else text[:limit].rsplit(' ',1)[0]+'…'

def description(row,evidence):
    kind=row['kind'];path=explanation_path(kind,evidence)
    try:
        prepared=json.loads(path.read_text(encoding='utf-8'))
        if prepared.get('scope_key')==scope_key(kind,evidence) and prepared.get('version')==VERSION and isinstance(prepared.get('summary'),str) and prepared['summary'].strip():
            return dict(title=prepared.get('title') or row['title'],reason=prepared['summary'],prepared=True,
                evidence=[dict(source=e['lang'].upper(),quote=first_statement(e['quote']),url=e.get('url','')) for e in evidence])
    except (OSError,ValueError,TypeError):pass
    statements=[]
    for source in evidence:
        wording=source['quote']
        label=source['lang'].upper()
        statements.append(label+': “'+first_statement(wording)+'”')
    criteria={
        'coverage':'The selected passages include different amounts or kinds of context. Compare the specific details above; a shorter excerpt does not establish that information is absent from the full article.',
        'framing':'Review how these passages attribute, evaluate or emphasize the same subject. A framing finding needs a material difference; ordinary translation or paraphrase is insufficient.',
        'contradiction':'Review whether these statements make incompatible assertions about the same event, time and scope. Different milestones, added detail and reported claims can be compatible.',
    }
    section=next((e.get('section') for e in evidence if e['lang']=='en' and e.get('section') not in ('Introduction','Background')),None)
    title=(section+': '+{'coverage':'compare the additional detail','framing':'compare the account','contradiction':'check the assertions'}.get(kind,'compare the passages')) if section else row['title']
    caution=[];scores=row.get('evidence',{}).get('scores',{})
    if kind=='contradiction' and scores.get('compatible',{}).get('probability',0)>=.8:
        caution.append('The classifier also strongly judged these claims compatible. Its signals conflict; this finding is uncertain and needs review.')
    if any(e.get('lang')=='fi' and str(e.get('section','')).strip().casefold()=='aiheesta muualla' for e in evidence):
        caution.append('A selected counterpart comes from a reference/link section. This is inadequate evidence for a missing-context claim.')
    return dict(title=title,reason='\n\n'.join(caution+statements+[criteria.get(kind,'Compare the exact source passages and their context.')]),prepared=False,
        evidence=[dict(source=e['lang'].upper(),quote=first_statement(e['quote']),url=e.get('url','')) for e in evidence])

def translation_sources(evidence):
    from local_translation import cached_translation
    result=[]
    for original in evidence:
        if original['lang']=='en':continue
        units=paragraphs(original)
        for source in units:
            try:cached=cached_translation(source['quote'],source['lang'])
            except Exception:cached=None
            legacy=original.get('translation') if len(units)==1 else ''
            result.append(dict(key=source_key(source),lang=source['lang'],text=cached['text'] if cached else legacy or '',
                model=cached['model'] if cached else '',cached=bool(cached or legacy)))
    return result

def translate_source(row,key):
    if row.get('mode') not in ('language','snapshot'):raise ValueError('Only original language passages can be translated here.')
    sources=[unit for original in row.get('evidence',{}).get('evidence',[]) for unit in paragraphs(original)]
    source=next((e for e in sources if source_key(e)==key and e['lang']!='en'),None)
    if source is None:raise LookupError('This source does not belong to the selected observation.')
    from local_translation import translate
    return dict(translate(source['quote'],source['lang']),source_key=key,lang=source['lang'],observation=row['observation'])

"""Stored question matrix and explicit, local hybrid search. No Decisions calls."""
from functools import lru_cache
from collections import Counter
import json
import math
import re
import threading
import unicodedata
from urllib.parse import urlencode

from skyline import RANK, LABELS, question_label, occurrence_choice, left_language

_catalogs={}
_lock=threading.Lock()


def catalog(data,languages):
    """One bulk metadata read, no per-cell source fetches or inference."""
    key=(data['run'],tuple(sorted(languages)),json.dumps(data.get('progress',{}),sort_keys=True))
    with _lock:
        if key in _catalogs:return _catalogs[key]
    selected=set(languages);rows=[];identities={}
    for row in data['rows']:
        cells=[];candidates=[]
        for phase in row['phases']:
            pairs=[p for p in phase.get('pairs',[]) if {e['lang'] for e in p['evidence']}<=selected and len({e['lang'] for e in p['evidence']})>=2 and p['kind'] in RANK]
            if not pairs:continue
            kind=max((p['kind'] for p in pairs),key=RANK.get)
            supporting=[p for p in pairs if p['kind']==kind]
            supporting.sort(key=lambda p:(not any(e['lang']=='en' for e in p['evidence']),p['id']))
            occurrence=supporting[0]
            pair_kinds={}
            for p in pairs:
                name='–'.join(sorted({e['lang'].upper() for e in p['evidence']}))
                if name not in pair_kinds or RANK[p['kind']]>RANK[pair_kinds[name]]:pair_kinds[name]=p['kind']
            cells.append(dict(stamp=phase['start'],kind=kind,occurrences=len(pairs),pair_kinds=[dict(pair=p,kind=k) for p,k in sorted(pair_kinds.items())],
                pairs=sorted({'–'.join(sorted({e['lang'].upper() for e in p['evidence']})) for p in pairs}),
                supporting_pairs=sorted({'–'.join(sorted({e['lang'].upper() for e in p['evidence']})) for p in supporting})))
            candidates.append((RANK[kind],phase['start'],occurrence['id']))
        if cells:
            identities[row['id']]=max(candidates)[2]
            rows.append(dict(id=row['id'],title=row['title'],cells=cells))
    payloads={}
    if identities:
        from core import connect
        ids=sorted(set(identities.values()))
        with connect() as db,db.cursor() as cursor:
            for offset in range(0,len(ids),150):
                batch=ids[offset:offset+150]
                cursor.execute('SELECT id,payload FROM paired_occurrence WHERE run_id=%s AND id IN ('+','.join(['%s']*len(batch))+')',[data['run'],*batch])
                payloads.update({r['id']:json.loads(r['payload']) for r in cursor.fetchall()})
    for row in rows:
        occurrence=payloads.get(identities[row['id']],{})
        sources=[e for e in occurrence.get('evidence',[]) if e['lang'] in selected]
        if sources:row['title']=question_label(occurrence)
        row['_text']=' '.join([row['title'],*(str(e.get(k) or '') for e in sources for k in ('section','quote','translation'))])
        row['_vectors']=sorted({e['vector_id'] for e in sources if e.get('vector_id')})
    result=dict(rows=rows,run=data['run'])
    with _lock:
        if len(_catalogs)>=8:_catalogs.pop(next(iter(_catalogs)))
        _catalogs[key]=result
    return result


def public_catalog(data,languages):
    result=catalog(data,languages)
    return dict(run=result['run'],rows=[{k:v for k,v in row.items() if not k.startswith('_')} for row in result['rows']])


def tokens(text):
    return re.findall(r'\w+',unicodedata.normalize('NFKD',text.casefold()).encode('ascii','ignore').decode())


def lexical_scores(rows,query):
    """Small BM25 index over selected evidence and source-derived labels."""
    terms=set(tokens(query));documents=[Counter(tokens(r['_text'])) for r in rows]
    if not terms or not documents:return {}
    average=sum(sum(d.values()) for d in documents)/len(documents) or 1
    frequencies={t:sum(t in d for d in documents) for t in terms}
    result={}
    for row,document in zip(rows,documents):
        length=sum(document.values());score=0
        for term in terms:
            tf=document[term];idf=math.log(1+(len(rows)-frequencies[term]+.5)/(frequencies[term]+.5))
            score+=idf*tf*2.2/(tf+1.2*(.25+.75*length/average)) if tf else 0
        if score:result[row['id']]=score
    return result


@lru_cache(maxsize=128)
def query_vector(query):
    # Explicit search only. Local-files-only prevents an implicit model download.
    from prepare import embedding_model
    from core import vector_bytes
    with _lock:
        model=embedding_model(local_files_only=True)
        return vector_bytes(next(iter(model.embed(['query: '+query],batch_size=1))))


def semantic_scores(rows,query):
    from core import connect
    ids=sorted({v for row in rows for v in row['_vectors']})
    if not ids:return {}
    vector=query_vector(query)
    with connect() as db,db.cursor() as cursor:
        cursor.execute('SELECT id,1-VEC_DISTANCE_COSINE(embedding,%s) similarity FROM divergence_vector WHERE id IN ('+','.join(['%s']*len(ids))+') ORDER BY VEC_DISTANCE_COSINE(embedding,%s)+0',[vector,*ids,vector])
        similarities={r['id']:float(r['similarity']) for r in cursor.fetchall()}
    return {row['id']:max((similarities.get(v,0) for v in row['_vectors']),default=0) for row in rows}


def hybrid_search(rows,query):
    query=query.strip()
    if not 2<=len(query)<=240:raise ValueError('Search with 2–240 characters.')
    lexical=lexical_scores(rows,query);mode='hybrid';warning=''
    try:semantic=semantic_scores(rows,query)
    except Exception:
        semantic={};mode='keywords';warning='Semantic search is unavailable locally. Showing keyword matches.'
    # Reciprocal rank fusion combines unlike score scales; scores are relevance only.
    ranked_lex=sorted(lexical,key=lambda k:(-lexical[k],k))
    ranked_sem=sorted((k for k in semantic if semantic[k]>=.72),key=lambda k:(-semantic[k],k))[:40]
    scores={}
    for ranking in (ranked_lex,ranked_sem):
        for index,identity in enumerate(ranking):scores[identity]=scores.get(identity,0)+1/(60+index+1)
    return dict(mode=mode,warning=warning,query=query,matches=[dict(id=k,relevance=scores[k]) for k in sorted(scores,key=lambda k:(-scores[k],k))],
                searched=len(rows),semantic_candidates=len(ranked_sem))


def cell_detail(data,languages,group,stamp,current,back,pair='all',kind='all'):
    from paired_history import detail
    from review_view import highlight_source
    row=next((r for r in catalog(data,languages)['rows'] if r['id']==group),None)
    cell=next((c for c in row['cells'] if c['stamp']==stamp),None) if row else None
    if not cell:raise LookupError('No stored finding for this question at this observation.')
    eligible=[p for p in cell['pair_kinds'] if (pair=='all' or p['pair']==pair) and (kind=='all' or p['kind']==kind)]
    if not eligible:raise LookupError('No stored finding supports this pair/category selection.')
    category=max((p['kind'] for p in eligible),key=RANK.get)
    eligible_pairs={p['pair'] for p in eligible if p['kind']==category}
    stored=detail(data['run'],group,stamp,languages=languages)
    supported=[o for o in stored['occurrences'] if o['kind']==category and '–'.join(sorted(e['lang'].upper() for e in o['evidence'])) in eligible_pairs] if stored else []
    occurrence=occurrence_choice(supported,languages,current,category)
    if not occurrence:raise LookupError('The source occurrence is unavailable.')
    left=left_language(occurrence,current)
    evidence=sorted(occurrence['evidence'],key=lambda e:(e['lang']!=left,e['lang']))
    for e in evidence:
        if e.get('stamp','')>stamp or e.get('url')!=f"https://{e['lang']}.wikipedia.org/w/index.php?oldid={e['revision']}":
            raise LookupError('Stored source revision does not match this observation.')
        e['quote_html']=str(highlight_source(e['quote'],e.get('highlights',[])))
    query=[('lang',left),('run',data['run']),('group',group),('stamp',stamp),('occurrence',occurrence['id']),('skyline',back)]
    query.extend(('languages',l) for l in languages)
    return dict(id=group,stamp=stamp,title=question_label(occurrence),kind=occurrence['kind'],label=LABELS[occurrence['kind']],
        evidence=evidence,occurrences=len(supported),destination=' ↔ '.join(e['lang'].upper() for e in evidence),
        href='/langcompare/'+data['topic']['id']+'?'+urlencode(query))

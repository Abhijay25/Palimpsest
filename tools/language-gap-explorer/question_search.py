"""Persisted question search. Explicit local vector search; no paid calls."""
import json
import re
import unicodedata

from core import connect

VERSION='question-search-v1'
STOPWORDS=set('a an the of to in on and or is are was were do does did who what when where why how which with for by from this that as at it many'.split())


def init():
    with connect() as db,db.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS question_search_document (
          article_id VARCHAR(24) NOT NULL,group_id CHAR(64) NOT NULL,
          title VARCHAR(500) NOT NULL,scope LONGTEXT,body MEDIUMTEXT NOT NULL,
          evidence LONGTEXT NOT NULL,document_hash CHAR(64) NOT NULL,terms LONGTEXT,vectors LONGTEXT,
          updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY(article_id,group_id),KEY article_title(article_id,title(160)),
          FULLTEXT KEY question_text(title,body)) CHARACTER SET utf8mb4""")
        c.execute('ALTER TABLE question_search_document ADD COLUMN IF NOT EXISTS terms LONGTEXT')
        c.execute('ALTER TABLE question_search_document ADD COLUMN IF NOT EXISTS vectors LONGTEXT')


def upsert_documents(topic,packets,labels_map):
    from question_titles import digest
    with connect() as db,db.cursor() as c:
        for packet in packets:
            label=labels_map.get(packet['group_id'],{})
            title=label.get('title') if label.get('status')=='accepted' else packet['fallback']
            scope=label.get('scope',{}) if label.get('status')=='accepted' else {}
            evidence=packet['evidence']
            body=' '.join([*(str(v) for v in scope.values()),*(str(e.get(k) or '') for e in evidence for k in ('section','text','translation'))])
            languages=sorted({e['lang'] for e in evidence})
            terms={lang:sorted(set(normalized_tokens(' '.join(str(e.get(k) or '') for e in evidence if e['lang']==lang for k in ('section','text','translation'))))) for lang in languages}
            vectors={lang:sorted({e['vector_id'] for e in evidence if e['lang']==lang and e.get('vector_id')}) for lang in languages}
            document=dict(title=title,scope=scope,evidence=evidence,body=body)
            c.execute("""INSERT INTO question_search_document(article_id,group_id,title,scope,body,evidence,document_hash,terms,vectors)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
              title=IF(document_hash<>VALUES(document_hash),VALUES(title),title),
              scope=IF(document_hash<>VALUES(document_hash),VALUES(scope),scope),
              body=IF(document_hash<>VALUES(document_hash),VALUES(body),body),
              evidence=IF(document_hash<>VALUES(document_hash),VALUES(evidence),evidence),
              terms=VALUES(terms),vectors=VALUES(vectors),
              document_hash=VALUES(document_hash)""",
              (topic,packet['group_id'],title,json.dumps(scope,ensure_ascii=False),body,json.dumps(evidence,ensure_ascii=False),digest([VERSION,document]),json.dumps(terms,ensure_ascii=False),json.dumps(vectors)))


def normalized_tokens(value):
    text=''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
    return re.findall(r'\w+',text)


def scoped_document(row,languages):
    selected=set(languages)
    if row.get('terms') and row.get('vectors'):
        terms=json.loads(row['terms']);vectors=json.loads(row['vectors'])
        available=set(normalized_tokens(row['title']))
        for lang in selected:available.update(terms.get(lang,[]))
        return dict(id=row['group_id'],title=row['title'],_tokens=available,
            _vectors=sorted({v for lang in selected for v in vectors.get(lang,[])}))
    evidence=[e for e in json.loads(row.get('evidence') or '[]') if e['lang'] in selected]
    return dict(id=row['group_id'],title=row['title'],
        text=' '.join([row['title'],*(str(e.get(k) or '') for e in evidence for k in ('section','text','translation'))]),
        _vectors=sorted({e['vector_id'] for e in evidence if e.get('vector_id')}))


def fuse(keyword,semantic):
    scores={}
    for ranking in (sorted(keyword,key=lambda k:(-keyword[k],k)),
                    sorted((k for k in semantic if semantic[k]>=.72),key=lambda k:(-semantic[k],k))[:40]):
        for i,identity in enumerate(ranking):scores[identity]=scores.get(identity,0)+1/(61+i)
    return [dict(id=k,relevance=scores[k]) for k in sorted(scores,key=lambda k:(-scores[k],k))]


def search(topic,languages,eligible_ids,query,mode='keyword'):
    query=query.strip()
    if not 2<=len(query)<=240:raise ValueError('Search with 2–240 characters.')
    if mode not in ('keyword','hybrid'):raise ValueError('Unknown search mode.')
    ids=sorted(set(eligible_ids))
    if not ids:return dict(matches=[],mode=mode,warning='')
    documents=[];keyword={}
    all_terms=set(normalized_tokens(query));terms=all_terms-STOPWORDS or all_terms
    try:
        with connect() as db,db.cursor() as c:
            for offset in range(0,len(ids),200):
                batch=ids[offset:offset+200];placeholders=','.join(['%s']*len(batch))
                # Scope before ranking; persisted FULLTEXT avoids rebuilding BM25 each request.
                c.execute('SELECT group_id,title,terms,vectors,IF(terms IS NULL,evidence,NULL) evidence,MATCH(title,body) AGAINST(%s IN NATURAL LANGUAGE MODE) lexical FROM question_search_document WHERE article_id=%s AND group_id IN ('+placeholders+')',[query,topic,*batch])
                for row in c.fetchall():
                    document=scoped_document(row,languages);documents.append(document)
                    available=document.get('_tokens') or set(normalized_tokens(document['text']))
                    last=normalized_tokens(query)[-1] if normalized_tokens(query) else ''
                    matched={term for term in terms if term in available or (term==last and len(term)>=3 and any(word.startswith(term) for word in available))}
                    overlap=len(matched)
                    if terms and terms<=matched:
                        # Local selected-language check prevents an unselected excerpt supplying a match.
                        keyword[row['group_id']]=float(row['lexical'] or 0)+overlap/len(terms)
    except Exception as error:
        if getattr(error,'args',[None])[0]==1146:
            return dict(matches=[],mode='keyword',warning='Question search documents have not been prepared yet.')
        raise
    semantic={};warning=''
    if mode=='hybrid':
        try:
            from heatmap import semantic_scores
            semantic=semantic_scores(documents,query)
        except Exception:
            mode='keyword';warning='Semantic search is unavailable locally. Showing keyword matches.'
    return dict(matches=fuse(keyword,semantic),mode=mode,warning=warning,searched=len(documents))

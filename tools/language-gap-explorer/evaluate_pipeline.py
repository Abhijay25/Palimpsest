"""Controlled synthetic calibration; real-world accuracy still needs bilingual review."""
import json
from pathlib import Path
from core import connect,ROOT
from pipeline import init,prepare_topic
from live_api import decisions

def run():
    init()
    cases=[]
    for name in ('A','B','C','D'):
        cases += [
          (f'The {name} law was adopted in 1999.',f'The {name} law took effect in 2000.',False),
          (f'The {name} law was adopted in 1999.',f'The {name} law was adopted in 2000.',True),
          (f'The population of {name} was 100 in 2020.',f'The population of {name} was 110 in 2021.',False),
          (f'The population of {name} was exactly 100 in 2020.',f'The population of {name} was exactly 110 in 2020.',True),
          (f'The {name} proposal was rejected.',f'The {name} proposal was approved.',True),
          (f'The {name} proposal was rejected in 2010.',f'The {name} proposal was approved in 2012.',False),
          (f'The {name} school taught in Swedish in 1888.',f'Swedish was the teaching language at {name} in 1888.',False),
          (f'The {name} school taught ONLY in Swedish in 1888.',f'The {name} school taught ONLY in Finnish in 1888.',True),
          (f'The {name} application was submitted in 2023.',f'The {name} minority was recognized in 2000.',False),
          (f'The {name} application was submitted in October 2023.',f'The same {name} application was submitted in November 2023.',True),
        ]
    questions=[{'type':'predicate','name':f'case{i}',
      'instructions':f'Do the two assertions in case {i} logically conflict? Only say yes for incompatible facts about the same event, time and scope. Adoption and entry into force, different years of a population count, and separate applications/recognitions can all be compatible.'} for i in range(len(cases))]
    result=decisions([{'id':i,'a':a,'b':b} for i,(a,b,_) in enumerate(cases)],questions)
    scores=[result[f'case{i}']['probability'] for i in range(len(cases))]
    negatives=[score for score,(_,_,truth) in zip(scores,cases) if not truth]
    positives=[score for score,(_,_,truth) in zip(scores,cases) if truth]
    false_conflict=sum(score>=.8 for score in negatives)/len(negatives)
    # Multilingual counterpart retrieval on exact vectors with two different facts.
    from prepare import embedding_model
    from core import vector_bytes
    model=embedding_model()
    triples=[('Finland became independent in 1917.','Suomi itsenäistyi vuonna 1917.','Finland blev självständigt år 1917.'),
      ('Schools switched to Swedish in 1888.','Koulut siirtyivät ruotsinkieliseen opetukseen vuonna 1888.','Skolorna övergick till svenska år 1888.'),
      ('The application was submitted in October 2023.','Hakemus jätettiin lokakuussa 2023.','Ansökan lämnades in i oktober 2023.'),
      ('The population was 100 people in 2020.','Väkiluku oli 100 asukasta vuonna 2020.','Befolkningen var 100 personer år 2020.')]
    vectors=list(model.embed(['query: '+t for triple in triples for t in triple]))
    hits1=hits3=total=0
    with connect() as db,db.cursor() as c:
        for i in range(len(triples)):
            for source in range(3):
                for target in range(3):
                    if source==target: continue
                    ranked=[]
                    for j in range(len(triples)):
                        c.execute('SELECT VEC_DISTANCE_COSINE(%s,%s) AS distance',(vector_bytes(vectors[i*3+source]),vector_bytes(vectors[j*3+target])))
                        ranked.append((float(c.fetchone()['distance']),j))
                    ranks=[j for _,j in sorted(ranked)]; hits1+=ranks[0]==i; hits3+=i in ranks[:3]; total+=1
    report={'type':'synthetic_controlled','decision_cases':len(cases),'false_conflict_rate_at_0.8':false_conflict,
      'conflict_recall_at_0.8':sum(s>=.8 for s in positives)/len(positives),
      'counterpart_recall_at_1':hits1/total,'counterpart_recall_at_3':hits3/total,
      'retrieval_queries':total,'scores':scores,'human_review':'Not yet validated on 20 real bilingual groups.'}
    report['passed']=false_conflict<=.1 and hits3/total>=.9
    with connect() as db,db.cursor() as c:
        c.execute('REPLACE INTO review_evaluation VALUES (1,%s,%s)',(report['passed'],json.dumps(report)))
        c.execute("SELECT payload,judgments FROM review_group WHERE status='done' LIMIT 20")
        review=c.fetchall()
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports'/'evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'reports'/'bilingual-review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': run()

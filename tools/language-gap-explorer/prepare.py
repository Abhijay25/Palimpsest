"""Download once, import idempotently, then embed a bounded set of topics."""
import argparse
import hashlib
import os
from functools import lru_cache
import requests
import pyarrow.parquet as pq
from core import ROOT, LANGS, MODEL, connect, init_db, split_passages, vector_bytes

RELEASE = 'https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/s-2026-10'

def download():
    folder = ROOT / 'data'
    folder.mkdir(exist_ok=True)
    sums = requests.get(f'{RELEASE}/SHA256SUMS', timeout=60)
    sums.raise_for_status()
    checks = {line.split()[-1].lstrip('*'):line.split()[0] for line in sums.text.splitlines() if len(line.split())==2}
    for lang in LANGS:
        name = f'articles-{lang}.parquet'
        dest = folder / name
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()==checks.get(name):
            continue
        print('Downloading', name, flush=True)
        with requests.get(f'{RELEASE}/{name}', stream=True, timeout=(15,120)) as r:
            r.raise_for_status()
            with open(str(dest)+'.part','wb') as f:
                for chunk in r.iter_content(1024*1024): f.write(chunk)
        partial = folder / (name+'.part')
        if hashlib.sha256(partial.read_bytes()).hexdigest()!=checks.get(name):
            raise ValueError(f'Checksum failed: {name}')
        os.replace(partial,dest)

def load():
    with connect() as db, db.cursor() as c:
        for lang in LANGS:
            c.execute('SELECT COUNT(*) AS n FROM article WHERE lang=%s',(lang,))
            path = ROOT/'data'/f'articles-{lang}.parquet'
            if c.fetchone()['n'] == pq.ParquetFile(path).metadata.num_rows:
                print('Already imported',lang,flush=True); continue
            for batch in pq.ParquetFile(path).iter_batches(batch_size=100):
                rows=[]
                for r in batch.to_pylist():
                    rows.append(tuple(r.get(k) if k!='date_modified' else str(r.get(k) or '') for k in
                       ('lang','page_id','rev_id','wikidata_id','title','url','date_modified','text')))
                c.executemany('INSERT IGNORE INTO article VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',rows)
            print('Imported',lang,flush=True)

@lru_cache(maxsize=1)
def embedding_model():
    # Keep Hugging Face cache inside the project, including restricted environments.
    os.environ.setdefault('HF_HOME',str(ROOT/'model-cache'/'huggingface'))
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    # FastEmbed's Python registry lacks e5-small; register its public ONNX export.
    if not any(description['model']==MODEL for description in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(model=MODEL, pooling=PoolingType.MEAN,
            normalization=True, sources=ModelSource(hf='Xenova/multilingual-e5-small'),
            dim=384, model_file='onnx/model_quantized.onnx',
            description='Multilingual E5 small, quantized ONNX export', license='mit',size_in_gb=.118)
    model = TextEmbedding(model_name=MODEL, cache_dir=str(ROOT/'model-cache'), threads=4)
    return model

def embed_topics(topics, rebuild=False):
    model = embedding_model()
    tokenizer = model.model.tokenizer
    with connect() as db, db.cursor() as c:
        for topic in topics:
            c.execute('SELECT * FROM article WHERE wikidata_id=%s ORDER BY lang',(topic,))
            for article in c.fetchall():
                key=(article['lang'],article['page_id'])
                if rebuild:
                    c.execute('DELETE FROM passage WHERE lang=%s AND page_id=%s',key)
                c.execute('SELECT COUNT(*) AS n FROM passage WHERE lang=%s AND page_id=%s AND model=%s',(*key,MODEL))
                if c.fetchone()['n']:
                    print('Cached',article['title'],flush=True); continue
                parts=list(split_passages(article['text'], tokenizer))
                print('Embedding',article['lang'],article['title'],len(parts),'passages',flush=True)
                vectors=list(model.embed(['query: '+text for _,text in parts], batch_size=8))
                # One transaction per article prevents an interrupted job looking complete.
                db.begin()
                try:
                    for i,((heading,text),vector) in enumerate(zip(parts,vectors)):
                        c.execute('INSERT INTO passage VALUES (%s,%s,%s,%s,%s,%s,%s)',(*key,i,heading,text,MODEL,vector_bytes(vector)))
                    db.commit()
                except Exception:
                    db.rollback(); raise

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--topics',nargs='*')
    p.add_argument('--skip-download',action='store_true')
    p.add_argument('--rebuild',action='store_true',help='Recompute passage splits and embeddings')
    args=p.parse_args()
    init_db()
    if not args.skip_download: download()
    load()
    topics=args.topics
    if topics is None:
        with connect() as db, db.cursor() as c:
            c.execute('''SELECT wikidata_id FROM article WHERE wikidata_id IS NOT NULL
              GROUP BY wikidata_id HAVING COUNT(DISTINCT lang)=3
              AND MAX(CHAR_LENGTH(text)) BETWEEN 2500 AND 18000
              ORDER BY MAX(CHAR_LENGTH(text)) DESC LIMIT 5''')
            topics=[r['wikidata_id'] for r in c.fetchall()]
    embed_topics(topics,args.rebuild)

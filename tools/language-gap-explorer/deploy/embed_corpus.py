"""Explicit, resumable, offline CPU embeddings for the imported multilingual corpus.

This fills snapshot `passage` rows, not historical `divergence_vector` rows.
Nothing runs on import, and no provider credentials or APIs are used.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import LANGS, MODEL, ROOT, connect, split_passages, vector_bytes

POLICY = 'snapshot-e5-query-400-v1'
MIN_FREE = 512 * 1024 * 1024
TABLE = 'corpus_embedding_progress'


def disk_guard():
    if shutil.disk_usage(ROOT).free < MIN_FREE:
        raise RuntimeError('At least 512 MiB free space is required on the research volume.')


def load_model():
    # Match prepare.embedding_model's export, pooling, dimensions and normalization,
    # but explicitly forbid downloads and keep a single bounded CPU session.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ.setdefault('HF_HOME', str(ROOT / 'model-cache' / 'huggingface'))
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    if not any(item['model'] == MODEL for item in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(
            model=MODEL, pooling=PoolingType.MEAN, normalization=True,
            sources=ModelSource(hf='Xenova/multilingual-e5-small'), dim=384,
            model_file='onnx/model_quantized.onnx',
            description='Multilingual E5 small, quantized ONNX export',
            license='mit', size_in_gb=.118)
    return TextEmbedding(model_name=MODEL, cache_dir=str(ROOT / 'model-cache'),
                         threads=1, providers=['CPUExecutionProvider'], local_files_only=True)


def init():
    with connect() as db, db.cursor() as c:
        c.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
          lang CHAR(2) NOT NULL, page_id INT UNSIGNED NOT NULL,
          model VARCHAR(100) NOT NULL, topic VARCHAR(24) NOT NULL,
          source_hash CHAR(64) NOT NULL, source_rev BIGINT,
          policy VARCHAR(80) NOT NULL, expected_passages INT UNSIGNED NOT NULL DEFAULT 0,
          status VARCHAR(16) NOT NULL, error_type VARCHAR(80),
          updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY(lang,page_id,model), KEY(status), KEY(topic)
        ) CHARACTER SET utf8mb4''')


def eligible():
    marks = ','.join(['%s'] * len(LANGS))
    with connect() as db, db.cursor() as c:
        c.execute(f'''SELECT a.lang,a.page_id,a.rev_id,a.wikidata_id,
          SHA2(a.text,256) AS source_hash FROM article a JOIN (
            SELECT wikidata_id FROM article WHERE lang IN ({marks})
            AND wikidata_id IS NOT NULL AND wikidata_id <> ''
            GROUP BY wikidata_id HAVING COUNT(DISTINCT lang)>=2
          ) t ON t.wikidata_id=a.wikidata_id WHERE a.lang IN ({marks})
          ORDER BY a.wikidata_id,a.lang,a.page_id''', (*LANGS, *LANGS))
        return c.fetchall()


def completed(c, article):
    c.execute(f'''SELECT p.*,s.actual,s.matching,s.first_ordinal,s.last_ordinal
      FROM {TABLE} p CROSS JOIN (
        SELECT COUNT(*) AS actual,SUM(model=%s) AS matching,
        MIN(ordinal) AS first_ordinal,MAX(ordinal) AS last_ordinal
        FROM passage WHERE lang=%s AND page_id=%s
      ) s WHERE p.lang=%s AND p.page_id=%s AND p.model=%s''',
      (MODEL, article['lang'], article['page_id'], article['lang'], article['page_id'], MODEL))
    row = c.fetchone()
    if not row or row['status'] != 'complete' or row['policy'] != POLICY:
        return False
    if row['source_hash'] != article['source_hash'] or row['source_rev'] != article['rev_id']:
        return False
    n = row['expected_passages']
    return (row['actual'] == n and int(row['matching'] or 0) == n
            and (n == 0 or (row['first_ordinal'] == 0 and row['last_ordinal'] == n - 1)))


def valid_vector(blob):
    if blob is None or len(blob) != 384 * 4:
        return False
    values = struct.unpack('<384f', blob)
    return all(math.isfinite(x) for x in values) and any(x != 0 for x in values)


def plan(parts, existing):
    """Preserve exact compatible cached rows; only missing/stale vectors need work."""
    if any(row['model'] != MODEL for row in existing):
        raise RuntimeError('Existing passage uses another model; refusing to overwrite it.')
    reusable = set()
    for row in existing:
        i = row['ordinal']
        if (0 <= i < len(parts) and (row['heading'], row['text']) == parts[i]
                and valid_vector(row['embedding'])):
            reusable.add(i)
    return reusable, [i for i in range(len(parts)) if i not in reusable]


def write_progress(c, article, status, n=0, error=None):
    c.execute(f'''INSERT INTO {TABLE}
      (lang,page_id,model,topic,source_hash,source_rev,policy,expected_passages,status,error_type)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE topic=VALUES(topic),source_hash=VALUES(source_hash),
      source_rev=VALUES(source_rev),policy=VALUES(policy),expected_passages=VALUES(expected_passages),
      status=VALUES(status),error_type=VALUES(error_type)''',
      (article['lang'], article['page_id'], MODEL, article['wikidata_id'],
       article['source_hash'], article['rev_id'], POLICY, n, status, error))


def process_article(article, get_model):
    """One edition commits atomically; crashes leave existing compatible rows intact."""
    disk_guard()
    lock = 'embed-corpus:' + hashlib.sha256(
        f"{article['lang']}:{article['page_id']}:{MODEL}".encode()).hexdigest()[:40]
    with connect() as db, db.cursor() as c:
        c.execute('SELECT GET_LOCK(%s,0) AS acquired', (lock,))
        if not c.fetchone()['acquired']:
            return {'status': 'busy', 'written': 0, 'reused': 0}
        try:
            if completed(c, article):
                return {'status': 'cached', 'written': 0, 'reused': 0}
            c.execute('SELECT text,rev_id,SHA2(text,256) AS source_hash FROM article '
                      'WHERE lang=%s AND page_id=%s', (article['lang'], article['page_id']))
            source = c.fetchone()
            if not source or source['source_hash'] != article['source_hash'] or source['rev_id'] != article['rev_id']:
                raise RuntimeError('Imported article changed; retry with fresh corpus inventory.')
            write_progress(c, article, 'running')
            model = get_model()
            parts = list(split_passages(source['text'], model.model.tokenizer))
            c.execute('SELECT ordinal,heading,text,model,embedding FROM passage '
                      'WHERE lang=%s AND page_id=%s', (article['lang'], article['page_id']))
            existing = c.fetchall()
            reusable, missing = plan(parts, existing)
            vectors = list(model.embed(['query: ' + parts[i][1] for i in missing], batch_size=8)) if missing else []
            if len(vectors) != len(missing):
                raise ValueError('Embedding result count differs from requested passage count.')
            encoded = [vector_bytes(v) for v in vectors]
            if not all(valid_vector(v) for v in encoded):
                raise ValueError('Invalid embedding dimensions or nonfinite/zero vector.')
            disk_guard()
            db.begin()
            try:
                # Lock source during publication; reject edits that occurred during inference.
                c.execute('SELECT rev_id,SHA2(text,256) AS source_hash FROM article '
                          'WHERE lang=%s AND page_id=%s FOR UPDATE', (article['lang'], article['page_id']))
                current = c.fetchone()
                if not current or current['source_hash'] != article['source_hash'] or current['rev_id'] != article['rev_id']:
                    raise RuntimeError('Imported article changed during embedding.')
                for row in existing:
                    if row['ordinal'] not in reusable:
                        c.execute('DELETE FROM passage WHERE lang=%s AND page_id=%s AND ordinal=%s AND model=%s',
                                  (article['lang'], article['page_id'], row['ordinal'], MODEL))
                rows = [(article['lang'], article['page_id'], i, *parts[i], MODEL, v)
                        for i, v in zip(missing, encoded)]
                if rows:
                    c.executemany('INSERT INTO passage '
                                  '(lang,page_id,ordinal,heading,text,model,embedding) '
                                  'VALUES (%s,%s,%s,%s,%s,%s,%s)', rows)
                write_progress(c, article, 'complete', len(parts))
                db.commit()
            except BaseException:
                db.rollback()
                raise
            return {'status': 'complete', 'written': len(missing), 'reused': len(reusable)}
        except Exception as error:
            # Never store raw exception strings (paths/connection details may contain secrets).
            write_progress(c, article, 'failed', error=type(error).__name__)
            raise
        finally:
            c.execute('SELECT RELEASE_LOCK(%s)', (lock,))


def durable_status():
    with connect() as db, db.cursor() as c:
        c.execute(f'SELECT status,COUNT(*) AS editions,SUM(expected_passages) AS passages '
                  f'FROM {TABLE} WHERE model=%s AND policy=%s GROUP BY status', (MODEL, POLICY))
        return [dict(status=row['status'], editions=int(row['editions']),
                     passages=int(row['passages'] or 0)) for row in c.fetchall()]


def run(limit=None):
    disk_guard()
    init()
    articles = eligible()
    topics = {}
    for article in articles:
        topics.setdefault(article['wikidata_id'], []).append(article)
    totals = dict(eligible_topics=len(topics), eligible_editions=len(articles),
                  attempted_topics=0, completed=0, cached=0, busy=0, failed=0,
                  written=0, reused=0)
    model = None

    def get_model():
        nonlocal model
        if model is None:
            model = load_model()
        return model

    print(json.dumps({'event': 'start', **totals}), flush=True)
    for topic, editions in topics.items():
        with connect() as db, db.cursor() as c:
            pending = [a for a in editions if not completed(c, a)]
        totals['cached'] += len(editions) - len(pending)
        if not pending:
            continue
        if limit is not None and totals['attempted_topics'] >= limit:
            break
        totals['attempted_topics'] += 1
        for article in pending:
            try:
                result = process_article(article, get_model)
                totals['completed' if result['status'] == 'complete' else result['status']] += 1
                totals['written'] += result['written']
                totals['reused'] += result['reused']
            except Exception as error:
                totals['failed'] += 1
                print(json.dumps({'event': 'edition_failed', 'topic': topic, 'lang': article['lang'],
                                  'error_type': type(error).__name__}), flush=True)
                # Missing offline model/disk should stop promptly, not fail the entire corpus.
                if model is None or shutil.disk_usage(ROOT).free < MIN_FREE:
                    raise RuntimeError('Offline model unavailable or disk guard reached; resume after fixing runtime.') from None
        print(json.dumps({'event': 'topic', 'topic': topic, **totals}), flush=True)
    print(json.dumps({'event': 'finish', **totals, 'durable': durable_status()}), flush=True)
    return totals


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('must be greater than zero')
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--limit', type=positive, help='Process at most N unfinished multilingual topics.')
    mode.add_argument('--all', action='store_true', help='Explicitly fill all eligible imported topics.')
    mode.add_argument('--status', action='store_true', help='Read durable progress; does not initialize schema or load models.')
    p.add_argument('--workers', type=int, choices=[1], default=1, help='One CPU-bounded worker only.')
    return p


def main():
    args = parser().parse_args()
    try:
        if args.status:
            print(json.dumps({'durable': durable_status()}))
            return 0
        return 1 if run(args.limit)['failed'] else 0
    except Exception as error:
        print(json.dumps({'event': 'stopped', 'error_type': type(error).__name__,
                          'hint': 'Check database/schema, preseeded offline model cache and 512 MiB free space.'}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Seed main-compatible article vectors from locked public assets, without inference.

Run on the VPS, explicitly --limit N or --all. This is an independent search
index: it neither imports wiki histories nor changes Library's three-book UI.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.parse
import urllib.request

LANGUAGES = ('en', 'fi', 'sv')
MODEL = 'bge-m3'
DIMENSIONS = 1024
RUNTIME = Path(os.environ.get('NEOWIKI_RESEARCH_ROOT', '/var/lib/neowiki'))
MIN_FREE = 512 * 1024 * 1024


class SeedValidationError(ValueError):
    """A static, safe diagnostic that contains no source data or credentials."""


class SeedRuntimeError(RuntimeError):
    """A static, safe runtime configuration diagnostic."""


def default_lock_path(script=None):
    # The repository has several ancestors; the production image only has
    # /app/deploy. Never index parents by a fixed depth during import.
    for parent in Path(script or __file__).resolve().parents:
        candidate = parent / 'datasets.lock.json'
        if candidate.is_file():
            return candidate
    return Path('/run/datasets.lock.json')


def connect():
    import pymysql
    # Fail closed when a research/wiki DB configuration is accidentally inherited.
    database = os.environ.get('LIBRARY_DB_NAME', os.environ.get('DB_NAME'))
    if database != 'library':
        raise SeedRuntimeError('Set DB_NAME=library (or LIBRARY_DB_NAME=library); other databases are refused.')
    password = os.environ.get('LIBRARY_DB_PASSWORD', os.environ.get('DB_PASSWORD'))
    secret = os.environ.get('LIBRARY_DB_PASSWORD_FILE', os.environ.get('DB_PASSWORD_FILE'))
    if secret:
        password = Path(secret).read_text(encoding='utf-8').strip()
    if not password:
        raise SeedRuntimeError('A Library database password or mounted password file is required.')
    return pymysql.connect(
        host=os.environ.get('LIBRARY_DB_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
        port=int(os.environ.get('LIBRARY_DB_PORT', os.environ.get('DB_PORT', '3306'))),
        user=os.environ.get('LIBRARY_DB_USER', os.environ.get('DB_USER', 'library')),
        password=password, database=database, charset='utf8mb4', autocommit=True,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=120, write_timeout=120)


def disk_guard(folder, incoming=0):
    existing = folder
    while not existing.exists():
        existing = existing.parent
    if shutil.disk_usage(existing).free < MIN_FREE + incoming:
        raise SeedRuntimeError('Keep at least 512 MiB free beyond the incoming asset size.')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_lock(path):
    raw = path.read_bytes()
    lock = json.loads(raw)
    if lock.get('repository') != 'MariaDB/mariadb-wikipedia-datasets' or not lock.get('tag'):
        raise SeedValidationError('Unexpected dataset repository/release.')
    assets = {a['name']: a for a in lock['assets']}
    for lang in LANGUAGES:
        for name in (f'articles-{lang}.parquet', f'vectors-bge-m3-{lang}.parquet'):
            a = assets[name]
            expected = f"https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/{lock['tag']}/{name}"
            if a['url'] != expected or not re.fullmatch('[0-9a-f]{64}', a['sha256']) or a['size'] <= 0:
                raise SeedValidationError('Invalid locked asset metadata.')
    return lock, hashlib.sha256(raw).hexdigest()


def asset_file(asset, folder):
    path = folder / asset['name']
    if path.exists() and path.stat().st_size == asset['size'] and digest(path) == asset['sha256']:
        return path
    disk_guard(folder, asset['size'])
    folder.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + '.part')
    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'NeoWiki-locked-catalog-seed/1'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                if out.tell() > asset['size']:
                    raise SeedValidationError('Asset exceeds locked size.')
        if partial.stat().st_size != asset['size'] or digest(partial) != asset['sha256']:
            raise SeedValidationError('Asset checksum/size mismatch; nothing imported.')
        partial.replace(path)
    finally:
        if partial.exists():
            partial.unlink()
    return path


def normalize(article, vector, lang):
    if article.get('lang') != lang or vector.get('lang') != lang or article['page_id'] != vector['page_id']:
        raise SeedValidationError('Article/vector language or source-page mismatch.')
    if vector.get('model') != MODEL or not isinstance(vector.get('truncated'), bool):
        raise SeedValidationError('Unexpected model or missing truncation provenance.')
    values = vector.get('embedding')
    if (not isinstance(values, (list, tuple)) or len(values) != DIMENSIONS
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
            or not any(values)):
        raise SeedValidationError('Expected a finite nonzero 1024-dimensional bge-m3 vector.')
    if not isinstance(article['page_id'], int) or article['page_id'] <= 0 or not isinstance(article['rev_id'], int) or article['rev_id'] <= 0:
        raise SeedValidationError('Invalid source page/anchor revision.')
    title = article.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 255:
        raise SeedValidationError('Invalid source title.')
    url = urllib.parse.urlparse(article.get('url', ''))
    if url.scheme != 'https' or url.hostname != f'{lang}.wikipedia.org':
        raise SeedValidationError('Invalid source Wikipedia URL.')
    timestamp = str(article.get('date_modified') or '')
    try:
        datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        raise SeedValidationError('Invalid source modification timestamp.') from None
    topic = article.get('wikidata_id')
    if topic is not None and not re.fullmatch(r'Q[1-9][0-9]*', topic):
        raise SeedValidationError('Malformed Wikidata identifier.')
    identity_kind = 'wikidata' if topic else 'source_page'
    # Preserve unlinked source articles without inventing Wikidata identifiers.
    topic = topic or f"{lang}:{article['page_id']}"
    return dict(topic_id=topic, language=lang, source_page_id=article['page_id'],
                source_revision_id=article['rev_id'], title=title, embedding=values,
                source_url=article['url'], source_timestamp=timestamp,
                text_hash=hashlib.sha256(article['text'].encode('utf-8')).hexdigest(),
                truncated=vector['truncated'], identity_kind=identity_kind)


def language_rows(article_path, vector_path, lang, expected_count):
    import pyarrow.parquet as pq
    articles = {}
    for batch in pq.ParquetFile(article_path).iter_batches(batch_size=256):
        for row in batch.to_pylist():
            if row['page_id'] in articles:
                raise SeedValidationError('Duplicate source article identity.')
            articles[row['page_id']] = row
    if len(articles) != expected_count:
        raise SeedValidationError('Article count differs from the locked corpus count.')
    seen = set()
    for batch in pq.ParquetFile(vector_path).iter_batches(batch_size=128):
        for vector in batch.to_pylist():
            page = vector['page_id']
            if page in seen or page not in articles:
                raise SeedValidationError('Duplicate/orphan source vector.')
            seen.add(page)
            yield normalize(articles[page], vector, lang)
    if seen != set(articles):
        raise SeedValidationError('Missing source article vectors.')


def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS library_articles (
      topic_id VARCHAR(32) NOT NULL,language CHAR(2) NOT NULL,
      source_page_id BIGINT UNSIGNED NOT NULL,source_revision_id BIGINT UNSIGNED NOT NULL,
      title VARCHAR(255) NOT NULL,embedding VECTOR(1024) NOT NULL,
      PRIMARY KEY(language,source_page_id),
      VECTOR INDEX library_semantic(embedding) M=16 DISTANCE=cosine) CHARACTER SET utf8mb4''')
    c.execute('''CREATE TABLE IF NOT EXISTS library_embedding_manifest (
      release_tag VARCHAR(80) NOT NULL,model VARCHAR(80) NOT NULL,dimensions INT NOT NULL,
      lock_sha256 CHAR(64) NOT NULL,manifest_json LONGTEXT NOT NULL,
      updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY(release_tag,model)) CHARACTER SET utf8mb4''')
    c.execute('''CREATE TABLE IF NOT EXISTS library_article_metadata (
      language CHAR(2) NOT NULL,source_page_id BIGINT UNSIGNED NOT NULL,
      model VARCHAR(80) NOT NULL,release_tag VARCHAR(80) NOT NULL,lock_sha256 CHAR(64) NOT NULL,
      source_revision_id BIGINT UNSIGNED NOT NULL,source_url VARCHAR(1000) NOT NULL,
      source_timestamp VARCHAR(80) NOT NULL,text_sha256 CHAR(64) NOT NULL,
      truncated BOOLEAN NOT NULL,identity_kind VARCHAR(24) NOT NULL,
      updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY(language,source_page_id)) CHARACTER SET utf8mb4''')


def publish(db, c, rows, lock, lock_hash):
    db.begin()
    try:
        c.executemany('''INSERT INTO library_articles
          (topic_id,language,source_page_id,source_revision_id,title,embedding)
          VALUES (%s,%s,%s,%s,%s,VEC_FromText(%s)) ON DUPLICATE KEY UPDATE
          topic_id=VALUES(topic_id),source_revision_id=VALUES(source_revision_id),
          title=VALUES(title),embedding=VALUES(embedding)''',
          [(r['topic_id'], r['language'], r['source_page_id'], r['source_revision_id'],
            r['title'], json.dumps(r['embedding'])) for r in rows])
        c.executemany('''INSERT INTO library_article_metadata
          (language,source_page_id,model,release_tag,lock_sha256,source_revision_id,
          source_url,source_timestamp,text_sha256,truncated,identity_kind)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
          model=VALUES(model),release_tag=VALUES(release_tag),lock_sha256=VALUES(lock_sha256),
          source_revision_id=VALUES(source_revision_id),source_url=VALUES(source_url),
          source_timestamp=VALUES(source_timestamp),text_sha256=VALUES(text_sha256),
          truncated=VALUES(truncated),identity_kind=VALUES(identity_kind)''',
          [(r['language'], r['source_page_id'], MODEL, lock['tag'], lock_hash,
            r['source_revision_id'], r['source_url'], r['source_timestamp'], r['text_hash'],
            r['truncated'], r['identity_kind']) for r in rows])
        db.commit()
    except BaseException:
        db.rollback()
        raise


def status(c):
    c.execute('SELECT language,COUNT(*) AS articles FROM library_articles GROUP BY language')
    counts = c.fetchall()
    c.execute('SELECT model,release_tag,identity_kind,COUNT(*) AS articles '
              'FROM library_article_metadata GROUP BY model,release_tag,identity_kind')
    return dict(articles=counts, provenance=c.fetchall(), dimensions=DIMENSIONS,
                viewer_note='Search index only; main Library still requires its separate verified-history catalog.')


def seed(lock_path, folder, limit=None):
    lock, lock_hash = read_lock(lock_path)
    assets = {a['name']: a for a in lock['assets']}
    written = reused = unlinked = 0
    with connect() as db, db.cursor() as c:
        init(c)
        c.execute('''INSERT INTO library_embedding_manifest
          (release_tag,model,dimensions,lock_sha256,manifest_json) VALUES (%s,%s,%s,%s,%s)
          ON DUPLICATE KEY UPDATE lock_sha256=VALUES(lock_sha256),manifest_json=VALUES(manifest_json)''',
          (lock['tag'], MODEL, DIMENSIONS, lock_hash, json.dumps(lock)))
        c.execute('''SELECT m.language,m.source_page_id FROM library_article_metadata m
          JOIN library_articles a ON a.language=m.language AND a.source_page_id=m.source_page_id
          AND a.source_revision_id=m.source_revision_id
          WHERE m.model=%s AND m.release_tag=%s AND m.lock_sha256=%s''', (MODEL, lock['tag'], lock_hash))
        done = {(r['language'], r['source_page_id']) for r in c.fetchall()}
        for lang in LANGUAGES:
            article_path = asset_file(assets[f'articles-{lang}.parquet'], folder)
            vector_path = asset_file(assets[f'vectors-bge-m3-{lang}.parquet'], folder)
            batch = []
            for row in language_rows(article_path, vector_path, lang, lock['expected_counts'][lang]):
                if (lang, row['source_page_id']) in done:
                    reused += 1
                    continue
                batch.append(row)
                if len(batch) >= 100 or (limit is not None and written + len(batch) >= limit):
                    disk_guard(folder)
                    publish(db, c, batch, lock, lock_hash)
                    written += len(batch)
                    unlinked += sum(r['identity_kind'] == 'source_page' for r in batch)
                    print(json.dumps(dict(event='batch', written=written, reused=reused, unlinked=unlinked)), flush=True)
                    batch = []
                    if limit is not None and written >= limit:
                        return dict(written=written, reused=reused, unlinked=unlinked, **status(c))
            if batch:
                disk_guard(folder)
                publish(db, c, batch, lock, lock_hash)
                written += len(batch)
                unlinked += sum(r['identity_kind'] == 'source_page' for r in batch)
        return dict(written=written, reused=reused, unlinked=unlinked, **status(c))


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be greater than zero')
    return number


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--limit', type=positive, help='Seed at most N missing article vectors (e.g.20).')
    mode.add_argument('--all', action='store_true', help='Seed the complete locked corpus explicitly.')
    mode.add_argument('--status', action='store_true', help='Read existing counts without creating schema/downloading.')
    p.add_argument('--lock', type=Path, default=default_lock_path(),
                   help='Repository lock if present, otherwise /run/datasets.lock.json (mount read-only in Docker).')
    p.add_argument('--assets', type=Path, default=RUNTIME / 'data' / 'bge-library')
    return p


def main():
    args = parser().parse_args()
    try:
        if args.status:
            with connect() as db, db.cursor() as c:
                print(json.dumps(status(c)))
            return 0
        if sys.platform != 'linux':
            raise SeedRuntimeError('Asset seeding is intended for the Linux VPS, not the local workstation.')
        print(json.dumps(seed(args.lock, args.assets, args.limit)), flush=True)
        return 0
    except Exception as error:
        diagnostic = dict(event='stopped', error_type=type(error).__name__,
                          hint='Check library DB settings, --lock (Docker mount /run/datasets.lock.json), VPS network and free disk.')
        if isinstance(error, (SeedValidationError, SeedRuntimeError)):
            diagnostic['message'] = str(error)
        elif error.args and type(error.args[0]) is int:
            # MariaDB numeric error codes are useful; driver strings may contain
            # connection identities or SQL values and are deliberately omitted.
            diagnostic['error_code'] = error.args[0]
        print(json.dumps(diagnostic), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

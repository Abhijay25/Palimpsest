"""Corpus storage and passage comparison. All application text stays local."""
import os
import re
import json
import struct
from pathlib import Path
import pymysql

ROOT = Path(__file__).resolve().parent
MODEL = 'intfloat/multilingual-e5-small'
LANGS = ('fi', 'en', 'sv')

def connect():
    return pymysql.connect(host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3310')), user=os.getenv('DB_USER', 'explorer'),
        password=os.getenv('DB_PASSWORD', 'local-explorer-only'),
        database=os.getenv('DB_NAME', 'language_gaps'), charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor, autocommit=True, connect_timeout=5, read_timeout=60, write_timeout=60)

def init_db():
    statements = [
    '''CREATE TABLE IF NOT EXISTS article (
      lang CHAR(2) NOT NULL, page_id INT UNSIGNED NOT NULL, rev_id BIGINT,
      wikidata_id VARCHAR(24), title VARCHAR(255), url VARCHAR(600),
      date_modified VARCHAR(60), text MEDIUMTEXT NOT NULL,
      PRIMARY KEY(lang,page_id), KEY topic(wikidata_id), KEY title(title)) CHARACTER SET utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS passage (
      lang CHAR(2) NOT NULL, page_id INT UNSIGNED NOT NULL, ordinal INT NOT NULL,
      heading VARCHAR(600), text TEXT NOT NULL, model VARCHAR(100) NOT NULL,
      embedding VECTOR(384) NOT NULL, PRIMARY KEY(lang,page_id,ordinal),
      VECTOR INDEX(embedding) DISTANCE=cosine) CHARACTER SET utf8mb4''',
    '''CREATE TABLE IF NOT EXISTS verification (
      wikidata_id VARCHAR(24) PRIMARY KEY, checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      result TEXT NOT NULL) CHARACTER SET utf8mb4''']
    with connect() as db, db.cursor() as c:
        for sql in statements: c.execute(sql)

def sections(text):
    heading, lines = 'Introduction', []
    for line in text.splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line)
        if match:
            if '\n'.join(lines).strip(): yield heading, '\n'.join(lines).strip()
            heading, lines = match[1], []
        else: lines.append(line)
    if '\n'.join(lines).strip(): yield heading, '\n'.join(lines).strip()

def split_passages(text, tokenizer):
    from tokenizers import Tokenizer
    # FastEmbed enables 512-token truncation and padding on its shared tokenizer.
    # Split with a clone so long sections are complete and inference stays padded.
    tokenizer = Tokenizer.from_str(tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    # E5's limit is 512 tokens; leave room for the passage prefix and special tokens.
    for heading, body in sections(text):
        if heading.casefold() in ('references', 'external links', 'lähteet', 'viitteet', 'källor', 'externa länkar'):
            continue
        encoded = tokenizer.encode(body, add_special_tokens=False)
        ids = encoded.ids
        for start in range(0, len(ids), 400):
            offsets=encoded.offsets[start:start+400]
            chunk = body[offsets[0][0]:offsets[-1][1]].strip()
            if chunk: yield heading[:600], chunk

def vector_bytes(v): return struct.pack('<384f', *v)

def compare(c, topic, source, target):
    c.execute('''SELECT p.ordinal, p.heading, p.text,
      t.ordinal AS target_ordinal, t.heading AS target_heading, t.text AS target_text,
      1 - VEC_DISTANCE_COSINE(p.embedding,t.embedding) AS similarity
      FROM passage p JOIN article a ON a.lang=p.lang AND a.page_id=p.page_id
      JOIN article b ON b.wikidata_id=a.wikidata_id AND b.lang=%s
      JOIN passage t ON t.lang=b.lang AND t.page_id=b.page_id AND t.model=p.model
      WHERE a.wikidata_id=%s AND p.lang=%s AND p.model=%s
      ORDER BY p.ordinal, similarity DESC, t.ordinal''', (target,topic,source,MODEL))
    best = {}
    for row in c.fetchall():
        if row['ordinal'] not in best:
            row['similarity'] = float(row['similarity'])
            best[row['ordinal']] = row
    return sorted(best.values(), key=lambda r:r['similarity'])

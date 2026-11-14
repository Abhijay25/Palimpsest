"""Extract the frozen three-topic catalog from checksum-verified S assets."""
import argparse
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq

TOPICS = ("Q110908561", "Q110908692", "Q4241896")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    catalog = {q: {'id': q, 'articles': {}} for q in TOPICS}
    locked = {a['name']: a for a in lock['assets']}
    for lang in ('fi', 'sv', 'en'):
        names = [f'articles-{lang}.parquet', f'vectors-bge-m3-{lang}.parquet']
        for name in names:
            path = args.assets / name
            assert hashlib.sha256(path.read_bytes()).hexdigest() == locked[name]['sha256'], f'Asset checksum failed: {name}'
        rows = [a for a in pq.read_table(args.assets / names[0]).to_pylist() if a.get('wikidata_id') in catalog]
        wanted = {a['page_id'] for a in rows}
        vectors = {a['page_id']: a for a in pq.read_table(args.assets / names[1]).to_pylist() if a['page_id'] in wanted}
        for article in rows:
            vector = vectors[article['page_id']]
            assert len(vector['embedding']) == 1024
            catalog[article['wikidata_id']]['articles'][lang] = {**article, 'embedding': vector['embedding'], 'embedding_model': vector['model'], 'embedding_truncated': vector['truncated']}
    for topic in catalog.values():
        assert set(topic['articles']) == {'fi', 'sv', 'en'}
        topic['title'] = topic['articles']['en']['title']
        topic['summary'] = topic['articles']['en']['text'].split('\n', 1)[-1].split('\n')[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix('.part')
    temp.write_text(json.dumps({'schema_version': 1, 'model': 'bge-m3', 'dimensions': 1024, 'release': lock['tag'], 'topics': list(catalog.values())}, ensure_ascii=False))
    temp.replace(args.output)
    print('Extracted three topics / nine snapshot-aligned article vectors')

if __name__ == '__main__':
    main()

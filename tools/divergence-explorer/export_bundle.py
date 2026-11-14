"""Export public, already-prepared prototype results. Never invoke inference.

Run in the prototype environment, whose core module supplies its DB connection:
python export_bundle.py --prototype-root /path/to/language-gap-explorer --output sample.json.gz
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

FORMAT = 'neowiki-divergence/v1'
EVIDENCE_FIELDS = ('lang', 'quote', 'section', 'start', 'end', 'revision', 'stamp', 'url',
                   'locations', 'translation', 'highlights', 'mark')


def public_evidence(evidence):
    result = {k: evidence[k] for k in EVIDENCE_FIELDS if k in evidence}
    if not re.fullmatch(r'https://(?:en|fi|sv|ru)\.wikipedia\.org/w/index\.php\?oldid=\d+', result.get('url', '')):
        raise ValueError('Every exported passage needs a public Wikipedia revision URL.')
    if not isinstance(result.get('quote'), str):
        raise ValueError('Every occurrence needs exact source text.')
    return result


def export(prototype_root, output):
    sys.path.insert(0, str(Path(prototype_root).resolve()))
    from core import connect
    from explore_preview import app
    with connect() as db, db.cursor() as cursor:
        cursor.execute("SELECT id,summary FROM paired_run WHERE topic='Q134949' AND version='symmetric-disagreements-v1' AND status='ready' ORDER BY updated DESC LIMIT 1")
        run = cursor.fetchone()
        if not run:
            raise ValueError('Prepare the symmetric Winter War replay first.')
        source = json.loads(run['summary'])
        # Explicit allowlist excludes cost/ledger data, local paths and secrets.
        summary = {k: source[k] for k in ('topic', 'mode', 'run', 'version', 'asOf', 'bounds', 'warning', 'rows', 'progress')}
        summary['coverage'] = {k: source['coverage'][k] for k in ('checkpoints', 'languages', 'complete_from', 'sampling')}
        summary['capabilities'] = {'enrichment': False}
        cursor.execute('SELECT id,topic_id,stamp,payload FROM paired_occurrence WHERE run_id=%s ORDER BY topic_id,stamp,id', (run['id'],))
        details = {}
        sources = {}
        for row in cursor.fetchall():
            payload = json.loads(row['payload'])
            occurrence = {k: payload[k] for k in ('scores', 'kind', 'question', 'similarity', 'sampled')}
            occurrence['id'] = row['id']
            occurrence['evidence'] = [public_evidence(e) for e in payload['evidence']]
            for evidence in occurrence['evidence']:
                if evidence['stamp'] > row['stamp']:
                    raise ValueError('Evidence is newer than its checkpoint.')
                sources[evidence['url']] = {'language': evidence['lang'], 'revision': evidence['revision'], 'url': evidence['url']}
            key = '|'.join((run['id'], row['topic_id'], row['stamp']))
            details.setdefault(key, []).append(occurrence)
    # The cached adapter is a read-only operation; it does not run the provider.
    with app.test_client() as client:
        response = client.get('/explore/api/cached?topic=Q2606233')
    snapshots = {}
    if response.status_code == 200:
        snapshot = response.get_json()
        for row in snapshot['rows']:
            for phase in row['phases']:
                phase['evidence'] = [public_evidence(e) for e in phase['evidence']]
                for e in phase['evidence']:
                    sources[e['url']] = {'language': e['lang'], 'revision': e['revision'], 'url': e['url']}
        snapshots['Q2606233'] = {k: snapshot[k] for k in ('topic', 'mode', 'asOf', 'rows', 'warning')}
    bundle = dict(format=FORMAT, histories={'Q134949': summary}, snapshots=snapshots, details=details,
                  provenance=dict(license='CC-BY-SA-4.0', attribution='Wikipedia contributors',
                                  sources=sorted(sources.values(), key=lambda s: s['url']),
                                  modifications='Rendered prose normalized and excerpted; model-assessed labels and provisional grouping added.'))
    raw = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(raw, mtime=0))
    manifest = dict(format=FORMAT, artifact=output.name, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    compressed_bytes=output.stat().st_size, decoded_bytes=len(raw),
                    topics=list(bundle['histories']), snapshots=list(snapshots),
                    tracks=len(summary['rows']), occurrences=sum(map(len, details.values())),
                    checkpoints=summary['coverage']['checkpoints'], bounds=summary['bounds'],
                    source_revisions=len(sources), license='CC-BY-SA-4.0', attribution='Wikipedia contributors',
                    policy='Historical samples and model judgments, not verified truth or continuous lifetimes. No secrets or API ledger are exported.')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prototype-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    export(args.prototype_root, args.output)

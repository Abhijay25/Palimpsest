"""Read-only semantic history viewer, with an optional explicitly connected engine."""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, request, session
import requests

ROOT = Path(__file__).resolve().parent
FORMAT = 'neowiki-divergence/v1'
LANGUAGES = {'en', 'fi', 'sv', 'ru'}
SEVERITY = {'coverage': 1, 'framing': 2, 'contradiction': 3}


def load_bundle(path):
    """Bundles are trusted operator inputs, never uploaded through the website."""
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        raw = stream.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024:
        raise ValueError('Bundle exceeds the 128 MiB decoded limit.')
    bundle = json.loads(raw)
    if bundle.get('format') != FORMAT:
        raise ValueError('Unsupported visualization bundle format.')
    if not all(isinstance(bundle.get(k), dict) for k in ('histories', 'snapshots', 'details')):
        raise ValueError('Bundle needs histories, snapshots and details maps.')
    return bundle


def scope_history(data, languages):
    """Filter actual pair occurrences, then recompute each period's label."""
    data = copy.deepcopy(data)
    selected = set(languages)
    rows = []
    for row in data['rows']:
        phases = []
        for phase in row['phases']:
            pairs = [p for p in phase['pairs'] if {e['lang'] for e in p['evidence']} <= selected]
            if not pairs:
                continue
            phase['pairs'] = pairs
            phase['occurrences'] = [p['id'] for p in pairs]
            phase['kind'] = max((p['kind'] for p in pairs), key=SEVERITY.get)
            phase['evidence'] = list({e['lang']: e for p in pairs for e in p['evidence']}.values())
            phases.append(phase)
        if phases:
            row['phases'] = phases
            row['languages'] = sorted({e['lang'] for p in phases for e in p['evidence']})
            rows.append(row)
    data['rows'] = rows
    data['capabilities'] = {'enrichment': False}
    return data


def identity(data):
    values = tuple(data.get(k, '') for k in ('run', 'group', 'stamp'))
    if not all(isinstance(v, str) for v in values):
        return None
    if not all(re.fullmatch(r'[a-f0-9]{64}', v) for v in values[:2]):
        return None
    if not re.fullmatch(r'[0-9TZ:+.\-]{10,35}', values[2]):
        return None
    return '|'.join(values)


class Engine:
    """Forward only known routes to an operator-configured loopback engine.

    The private engine remains responsible for its own job, visibility, provider,
    budget and enrichment policies. No credentials or arbitrary URL proxy exist.
    """
    def __init__(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('Engine URL must be an HTTP loopback origin, without credentials or path.')
        self.url = url.rstrip('/')
        self.lock = threading.Lock()

    def read(self, endpoint, args):
        response = requests.get(self.url + '/explore/api/' + endpoint,
                                params=list(args.items(multi=True)), timeout=(3, 15), allow_redirects=False)
        if response.is_redirect:
            raise ValueError('Engine redirects are not supported.')
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('Engine response must be a JSON object.')
        if response.ok and endpoint in ('history', 'cached'):
            result['capabilities'] = {'enrichment': endpoint == 'history'}
        return result, response.status_code

    def enrich(self, data):
        # A fresh engine-side session supplies its own token. Never forward the
        # browser's local session/token to another application.
        with self.lock, requests.Session() as client:
            page = client.get(self.url + '/explore', timeout=(3, 15), allow_redirects=False)
            page.raise_for_status()
            match = re.search(r'name="review-token" content="([a-f0-9]{48})"', page.text)
            if not match:
                raise ValueError('Engine did not supply an enrichment token.')
            response = client.post(self.url + '/explore/api/enrich', json=data,
                                   headers={'X-Review-Token': match[1]}, timeout=(3, 120), allow_redirects=False)
            if response.is_redirect:
                raise ValueError('Engine redirects are not supported.')
            return response.json(), response.status_code


def create_app(bundle=None, engine_url=None):
    app = Flask(__name__, root_path=str(ROOT))
    app.secret_key = secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=4096,
                      TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    data = bundle if bundle is not None else load_bundle(ROOT / 'sample' / 'wikipedia-history.json.gz')
    engine = Engine(engine_url) if engine_url else None

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/explore/api/'):
            response.headers['Cache-Control'] = 'no-store'
            if response.is_json and response.status_code == 200 and request.accept_encodings['gzip'] > 0:
                response.set_data(gzip.compress(response.get_data(), compresslevel=3, mtime=0))
                response.headers['Content-Encoding'] = 'gzip'
                response.headers['Vary'] = 'Accept-Encoding'
        return response

    def forward(endpoint):
        try:
            result, status = engine.read(endpoint, request.args)
            return jsonify(result), status
        except (requests.RequestException, ValueError):
            return jsonify(error='The configured local engine is unavailable. Check its address and preparation status.'), 503

    @app.get('/')
    def root():
        return redirect('/explore')

    @app.get('/explore')
    def page():
        from flask import render_template
        session.setdefault('review_token', secrets.token_hex(24))
        return render_template('discrepancy_explorer.html')

    @app.get('/explore/api/history')
    def history():
        topic = request.args.get('topic', '')
        languages = list(dict.fromkeys(request.args.getlist('languages') or ['en', 'fi', 'ru']))
        if not re.fullmatch(r'Q\d{1,15}', topic) or not 2 <= len(languages) <= 4 or not set(languages) <= LANGUAGES:
            return jsonify(error='Choose a valid topic and two to four supported editions.'), 400
        if engine:
            return forward('history')
        result = data['histories'].get(topic)
        if not result or not set(languages) <= set(result['topic']['languages']):
            return jsonify(error='This bundle has Winter War history for EN, FI and RU. Choose that sample, or connect a prepared local engine.'), 404
        return jsonify(scope_history(result, languages))

    @app.get('/explore/api/cached')
    def cached():
        topic = request.args.get('topic', '')
        if not re.fullmatch(r'Q\d{1,15}', topic):
            return jsonify(error='Choose a valid Wikipedia topic.'), 400
        if engine:
            return forward('cached')
        result = data['snapshots'].get(topic)
        if not result:
            return jsonify(error='No snapshot findings are included for this topic.'), 404
        result = copy.deepcopy(result)
        result['capabilities'] = {'enrichment': False}
        return jsonify(result)

    @app.get('/explore/api/details')
    def details():
        key = identity(request.args)
        languages = request.args.getlist('languages') or ['en', 'fi', 'ru']
        if not key or not 2 <= len(set(languages)) <= 4 or not set(languages) <= LANGUAGES:
            return jsonify(error='Invalid source occurrence or language selection.'), 400
        if engine:
            return forward('details')
        occurrences = [o for o in data['details'].get(key, []) if {e['lang'] for e in o['evidence']} <= set(languages)]
        if not occurrences:
            return jsonify(error='No stored occurrences match these languages.'), 404
        return jsonify(occurrences=occurrences, evidence=occurrences[0]['evidence'])

    @app.post('/explore/api/enrich')
    def enrich():
        if request.headers.get('Sec-Fetch-Site') == 'cross-site' or not secrets.compare_digest(
                request.headers.get('X-Review-Token', ''), session.get('review_token', 'invalid')):
            return jsonify(error='Reload the viewer before requesting enrichment.'), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not identity(payload) or not re.fullmatch(r'[a-f0-9]{64}', str(payload.get('occurrence', ''))):
            return jsonify(error='Select a stored source occurrence.'), 400
        if not engine:
            return jsonify(error='The bundled sample is read-only. Connect the local engine for new translations and evidence highlighting.'), 409
        # Only identities cross this boundary; arbitrary source text is discarded.
        payload = {k: payload[k] for k in ('run', 'group', 'stamp', 'occurrence')}
        try:
            result, status = engine.enrich(payload)
            return jsonify(result), status
        except (requests.RequestException, ValueError):
            return jsonify(error='Engine enrichment is unavailable. Original sources remain visible.'), 503

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'sample' / 'wikipedia-history.json.gz')
    parser.add_argument('--engine-url', help='Optional existing engine, e.g. http://127.0.0.1:8020')
    parser.add_argument('--port', type=int, default=8021)
    args = parser.parse_args()
    create_app(load_bundle(args.bundle), args.engine_url).run(host='127.0.0.1', port=args.port, debug=False)

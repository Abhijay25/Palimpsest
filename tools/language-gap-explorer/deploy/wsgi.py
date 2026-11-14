"""Public reader surface. Preparation and provider access belong to CLI workers."""
import os

from flask import jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

from app import app
from core import connect
import live_api


secret = os.environ.get('NEOWIKI_SESSION_SECRET', '')
if len(secret) < 32:
    raise RuntimeError('Set a persistent NEOWIKI_SESSION_SECRET of at least 32 characters.')
app.secret_key = secret
app.config.update(
    DEBUG=False,
    TESTING=False,
    TEMPLATES_AUTO_RELOAD=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('NEOWIKI_COOKIE_SECURE', '1') == '1',
    MAX_CONTENT_LENGTH=64 * 1024,
)
if os.environ.get('NEOWIKI_TRUST_PROXY', '0') == '1':
    # Only publish the reader on loopback behind exactly one trusted proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)


def no_provider(*args, **kwargs):
    raise live_api.APIError('Provider calls are disabled in the public reader. Use an explicit worker.')


# This also protects against accidental future calls from an allowed read route.
live_api.call = no_provider
live_api.key = no_provider

READ_ENDPOINTS = frozenset({
    'static', 'home', 'index', 'article_page', 'topic_page', 'reader_health',
    'discrepancy_explorer.page', 'discrepancy_explorer.skyline_overview',
    'discrepancy_explorer.zoom_articles', 'discrepancy_explorer.history_showcase',
    'discrepancy_explorer.lab_question_search', 'discrepancy_explorer.heatmap_matrix',
    'discrepancy_explorer.heatmap_cell',
})


@app.before_request
def reader_surface():
    allowed = (request.method in {'GET', 'HEAD'} and request.endpoint in READ_ENDPOINTS)
    allowed = allowed or (request.method == 'POST' and request.endpoint == 'watch.translation')
    if not allowed or request.args.get('demo') == '1':
        return jsonify(error='This public reader exposes stored findings only. Use explicit CLI workers for preparation.'), 404
    if request.endpoint == 'home':
        return redirect('/explore')


@app.get('/healthz', endpoint='reader_health')
def health():
    try:
        with connect() as db, db.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return jsonify(status='unavailable'), 503
    return jsonify(status='ready', mode='stored-reader')


@app.after_request
def reader_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    if request.endpoint != 'static':
        response.headers['Cache-Control'] = 'private, no-store'
    return response

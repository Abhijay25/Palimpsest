"""Private durable queue. Setup and recovery are explicit; reads never create files.

SQLite lives on the owned persistent local volume, separate from campaign ledgers.
Every provider attempt reserves a policy call slot before leaving this process.
An interrupted/failed attempt retains that slot and is never automatically retried.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

SUCCESS = ('completed', 'partial')
TERMINAL = (*SUCCESS, 'failed', 'held_unknown', 'blocked_policy', 'paused_disk', 'awaiting_index')


class RequestError(ValueError):
    """A safe, user-facing rejection with no provider response or credentials."""


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def root():
    value = os.environ.get('NEOWIKI_ON_DEMAND_ROOT')
    if not value:
        raise LookupError('On-demand jobs are not configured. Saved Issues remain readable.')
    return Path(value).resolve()


def policy():
    path = os.environ.get('NEOWIKI_ON_DEMAND_POLICY')
    if not path:
        return dict(version=1, enabled=False, authorization='No on-demand spending authorization configured.', engines={})
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if value.get('version') != 1 or not isinstance(value.get('engines'), dict):
        raise ValueError('Invalid on-demand policy.')
    for kind,engine in value['engines'].items():
        config=engine.get('configuration',{})
        allowed={'provider','model','reviewer_model','triage_model','prompt_version','policy_version','max_output_tokens'}
        if kind not in ('page','revision','language') or not isinstance(config,dict) or set(config)-allowed:
            raise ValueError('Invalid public engine configuration; credentials do not belong in policy.')
        if engine.get('enabled'):
            required={'provider','model','prompt_version','policy_version'}
            if kind!='language':required|={'reviewer_model','triage_model','max_output_tokens'}
            if not required<=set(config) or any(not isinstance(config[k],str) or not config[k] for k in required-{'max_output_tokens'}):
                raise ValueError('An enabled engine requires exact model, prompt and policy versions.')
            if kind!='language' and (type(config['max_output_tokens']) is not int or not 1<=config['max_output_tokens']<=32768):
                raise ValueError('A bounded detector output-token limit is required.')
    return value


def permit(config, current=None):
    p = policy() if current is None else current
    engine = p.get('engines', {}).get(config['kind'], {})
    # Exact immutable authorization revision is rechecked at enqueue, claim and
    # every provider call. Rotating/revoking a policy blocks outstanding work.
    if not p.get('enabled') or not engine.get('enabled'):
        return False, 'New on-demand inference is disabled by server policy.'
    if config.get('authorization') != digest(p):
        return False, 'The server policy changed. Prepare a new request.'
    if not p.get('authorization') or not engine.get('authorization'):
        return False, 'An explicit on-demand authorization record is required.'
    if config['topic'] not in engine.get('topics', []):
        return False, 'This article is outside the on-demand spending authorization.'
    if config['engine'] != engine.get('configuration'):
        return False, 'The requested engine configuration is no longer authorized.'
    limit = engine.get('max_provider_calls')
    if type(limit) is not int or limit <= 0:
        return False, 'A positive provider-call allowance is required; historical campaign approval does not apply.'
    if config['kind'] == 'language' and config['engine'].get('provider') != 'openai':
        return False, 'The language engine requires its explicit OpenAI configuration.'
    if config['kind'] in ('revision', 'page') and config['engine'].get('provider') != 'gemini':
        return False, 'The native detector worker requires its explicit Gemini configuration.'
    return True, engine['authorization']


@contextmanager
def database(write=False):
    path = root() / 'queue.sqlite'
    # mode=rw prohibits schema/file creation from GETs and ordinary requests.
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        if write:
            db.commit()
    except BaseException:
        if write:
            db.rollback()
        raise
    finally:
        db.close()


def init():
    folder = root()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(sqlite3.connect(folder / 'queue.sqlite')) as db:
        db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS plan(id TEXT PRIMARY KEY,scope TEXT NOT NULL,topic TEXT NOT NULL,
          config TEXT NOT NULL,sources TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS job(id TEXT PRIMARY KEY,base TEXT NOT NULL,previous TEXT,
          scope TEXT NOT NULL,topic TEXT NOT NULL,kind TEXT NOT NULL,config TEXT NOT NULL,sources TEXT NOT NULL,
          requester INTEGER NOT NULL,status TEXT NOT NULL,progress TEXT NOT NULL,result TEXT,error TEXT,
          created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS job_scope ON job(scope,topic,created);
        CREATE INDEX IF NOT EXISTS job_base ON job(base,created);
        CREATE TABLE IF NOT EXISTS attempt(id TEXT PRIMARY KEY,job TEXT NOT NULL REFERENCES job(id),
          authorization TEXT NOT NULL,kind TEXT NOT NULL,request_hash TEXT NOT NULL,
          request TEXT NOT NULL,status TEXT NOT NULL,response TEXT,error TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS attempt_allowance ON attempt(authorization,kind);
        ''')
        db.commit()
    (folder / 'queue.sqlite').chmod(0o600)


def source_identity(source):
    return {key: source.get(key) for key in ('lang', 'title', 'page_id', 'revision_id', 'parent_id', 'timestamp', 'sha256', 'parent_sha256')}


def validate_sources(sources):
    for source in sources:
        if hashlib.sha256(source['wikitext'].encode()).hexdigest() != source['sha256']:
            raise ValueError('Frozen source text hash mismatch.')
        if source.get('parent_sha256') and hashlib.sha256(source['parent_wikitext'].encode()).hexdigest() != source['parent_sha256']:
            raise ValueError('Frozen parent text hash mismatch.')


def save_plan(scope, config, sources):
    validate_sources(sources)
    config = dict(config, sources=[source_identity(s) for s in sources])
    identity = digest([scope, config])
    with database(True) as db:
        db.execute('INSERT INTO plan VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET created=excluded.created', (identity, scope, config['topic'], packed(config), packed(sources), time.time()))
    return dict(id=identity, configuration=config, allowed=permit(config)[0], message=permit(config)[1])


def public(row):
    item = dict(row)
    item['configuration'] = json.loads(item.pop('config'))
    item['progress'] = json.loads(item['progress'])
    item.pop('sources', None)
    item.pop('requester', None)
    item['result'] = json.loads(item['result']) if item.get('result') else None
    return item


def get(identity, scope, topic):
    if not re.fullmatch('[a-f0-9]{64}', str(identity)):
        raise ValueError('Invalid job identity.')
    with database() as db:
        row = db.execute('SELECT * FROM job WHERE id=? AND scope=? AND topic=?', (identity, scope, topic)).fetchone()
    if row is None:
        raise LookupError('This job is not available in this wiki/article scope.')
    return public(row)


def recent(scope, topic):
    with database() as db:
        rows = db.execute('SELECT * FROM job WHERE scope=? AND topic=? ORDER BY created DESC,id DESC LIMIT 30', (scope, topic)).fetchall()
    return [public(row) for row in rows]


def enqueue(plan_id, scope, topic, requester, previous=None):
    if type(requester) is not int or requester <= 0:
        raise RequestError('A registered native requester is required.')
    with database(True) as db:
        row = db.execute('SELECT * FROM plan WHERE id=? AND scope=? AND topic=?', (plan_id, scope, topic)).fetchone()
        if not row or time.time() - row['created'] > 1800:
            raise LookupError('Request preview expired. Prepare it again.')
        config = json.loads(row['config'])
        base = digest({k: v for k, v in config.items() if k != 'authorization'})
        identity = digest([base, previous])
        # A repeat POST recovers the same job even if policy was since revoked.
        existing = db.execute('SELECT * FROM job WHERE id=?', (identity,)).fetchone()
        if existing:
            if existing['scope'] != scope:
                raise LookupError('This exact job is already owned by another native wiki. No duplicate was queued.')
            return public(existing)
        allowed, message = permit(config)
        if not allowed:
            raise RequestError(message)
        unresolved = db.execute("SELECT id FROM job WHERE base=? AND status NOT IN ('completed','partial') LIMIT 1", (base,)).fetchone()
        if unresolved:
            raise RequestError('An earlier job is active, failed or unresolved. Inspect it; no duplicate or automatic retry was queued.')
        if previous:
            old = db.execute('SELECT * FROM job WHERE id=? AND scope=? AND topic=?', (previous, scope, topic)).fetchone()
            if not old or old['base'] != base or old['status'] != 'completed':
                raise RequestError('Rescan requires an exact successful complete job. Partial/failed/unknown requests require operator reconciliation.')
            if not policy()['engines'][config['kind']].get('allow_rescan'):
                raise RequestError('Fresh rescans are not authorized by server policy.')
        created = now()
        db.execute('INSERT INTO job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identity, base, previous, scope, topic, config['kind'], packed(config), row['sources'], requester, 'queued', packed(dict(stage='queued')), None, None, created, created))
    return get(identity, scope, topic)


def update(identity, status, progress=None, result=None, error=None):
    with database(True) as db:
        db.execute('UPDATE job SET status=?,progress=?,result=COALESCE(?,result),error=?,updated=? WHERE id=?',
                   (status, packed(progress or dict(stage=status)), packed(result) if result is not None else None, error, now(), identity))


def claim():
    with database(True) as db:
        row = db.execute("SELECT * FROM job WHERE status IN ('queued','awaiting_index') ORDER BY created,id LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE job SET status='running',progress=?,updated=? WHERE id=?", (packed(dict(stage='validating')), now(), row['id']))
            row = dict(row)
            row['config'] = json.loads(row['config'])
            row['sources'] = json.loads(row['sources'])
        return row


def recover_interrupted():
    # Called only while holding the exclusive worker process lock.
    with database(True) as db:
        for row in db.execute("SELECT id,result FROM job WHERE status='running'").fetchall():
            status = 'awaiting_index' if row['result'] or (root()/'results'/(row['id']+'.json')).is_file() else 'held_unknown'
            db.execute('UPDATE job SET status=?,error=?,updated=? WHERE id=?', (status, 'Worker interrupted; provider reservations retained. No provider request will be repeated.', now(), row['id']))


def reserve_attempt(job, request):
    allowed, message = permit(job['config'])
    if not allowed:
        raise ValueError(message)
    config = job['config']
    # Request identity includes exact source/config and a deliberate rescan generation.
    rid = digest([job['id'], request])
    authorization = config['authorization']
    limit = policy()['engines'][config['kind']]['max_provider_calls']
    with database(True) as db:
        old = db.execute('SELECT * FROM attempt WHERE id=?', (rid,)).fetchone()
        if old:
            if old['status'] == 'done':
                return rid, json.loads(old['response'])
            raise RuntimeError('An exact provider attempt failed or is unresolved. Its reservation is retained.')
        count = db.execute('SELECT COUNT(*) FROM attempt WHERE authorization=? AND kind=?', (authorization, config['kind'])).fetchone()[0]
        if count >= limit:
            raise RuntimeError('The on-demand provider-call allowance is exhausted. Reservations are retained.')
        created = now()
        db.execute('INSERT INTO attempt VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (rid, job['id'], authorization, config['kind'], digest(request), packed(request), 'reserved', None, None, created, created))
    return rid, None


def finish_attempt(identity, response=None, error=None):
    with database(True) as db:
        db.execute('UPDATE attempt SET status=?,response=?,error=?,updated=? WHERE id=?',
                   ('failed_or_unknown' if error else 'done', packed(response) if response is not None else None, error, now(), identity))

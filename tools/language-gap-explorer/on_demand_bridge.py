"""Native authenticated on-demand request planning; no provider calls here."""
import hashlib
import os
from pathlib import Path

import on_demand_jobs as jobs


def fetch_source(lang, revision):
    """Read shared immutable sources; acquire misses only into our owned volume."""
    import json
    from revision_text import cached_revision
    hit=cached_revision(lang,revision)
    if hit is not None:return hit
    path=jobs.root()/'sources'/f'{lang}-{int(revision)}.json'
    if path.is_file():return json.loads(path.read_text(encoding='utf-8'))
    from showcase_history import api
    answer=api(lang,dict(action='query',prop='revisions',revids=int(revision),rvprop='ids|content|timestamp',rvslots='main'))
    pages=answer['query']['pages'];page=pages[0] if isinstance(pages,list) else next(iter(pages.values()))
    item=page['revisions'][0];slot=item['slots']['main']
    text=slot.get('content',slot.get('*'))
    if not isinstance(text,str) or int(item['revid'])!=int(revision):raise LookupError('Exact source text is unavailable.')
    value=dict(revision_id=int(item['revid']),parent_id=item.get('parentid'),timestamp=item['timestamp'],title=page['title'],wikitext=text)
    path.parent.mkdir(exist_ok=True,mode=0o700)
    # SQLite plans freeze full sources transactionally. This opportunistic cache
    # is private and never replaces a shared flag/revision cache.
    import uuid
    temporary=path.with_suffix('.'+uuid.uuid4().hex+'.part')
    with temporary.open('x',encoding='utf-8') as stream:
        stream.write(jobs.packed(value));stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    return value


def implementation_identity():
    base = Path(__file__).resolve().parent
    names = ('on_demand_jobs.py', 'on_demand_bridge.py', 'on_demand_worker.py',
             'article_pipeline.py', 'paired_history.py', 'historical_divergence.py',
             'live_api.py', 'relationship_policy.py', 'candidate_eligibility.py', 'pipeline.py')
    files = {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in names}
    repo = base.parent.parent
    for directory in ('palimpsest', 'prompts'):
        for path in sorted((repo / directory).rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.txt', '.md', '.json') and '__pycache__' not in path.parts:
                files[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return jobs.digest(files)


def describe(topic):
    p = jobs.policy()
    return dict(enabled=p.get('enabled') is True, authorization=p.get('authorization', ''),
                engines={kind: dict(configuration=engine.get('configuration', {}),
                                    allowed=p.get('enabled') is True and engine.get('enabled') is True and topic in engine.get('topics', []),
                                    authorization=engine.get('authorization', ''),
                                    max_provider_calls=engine.get('max_provider_calls'),
                                    allow_rescan=engine.get('allow_rescan') is True)
                         for kind, engine in p['engines'].items()},
                notice='On-demand requests use a separate server authorization. Historical campaign allowances do not apply.')


def source_record(lang, revision, title=None, expected=None, page_id=None):
    record = dict(fetch_source(lang, int(revision)))
    if int(record.get('revision_id', 0)) != int(revision) or not isinstance(record.get('wikitext'), str):
        raise LookupError('Exact source revision content is unavailable.')
    if title is not None and record.get('title', '').replace('_', ' ') != title.replace('_', ' '):
        raise LookupError('Source revision title differs from the reconciled article.')
    sha = hashlib.sha256(record['wikitext'].encode()).hexdigest()
    if expected and (sha != expected.get('sha256') or record.get('timestamp') != expected.get('timestamp') or int(record.get('parent_id') or 0) != int(expected.get('parent_id') or 0)):
        raise LookupError('Source revision/parent/time/text differs from the native reconciliation. No substitute was selected.')
    return dict(record, lang=lang, sha256=sha, page_id=page_id)


def prepare(payload, topic):
    import shutil
    if shutil.disk_usage(jobs.root()).free < 30_000_000_000:
        raise LookupError('Preparation paused below 30 GB free disk space.')
    kind = payload.get('mode')
    if kind not in ('revision', 'page', 'language'):
        raise ValueError('Choose an edit scan, page check or language comparison.')
    ref = payload.get('source') or {}
    edition = payload['edition']
    if ref.get('lang') != edition or ref.get('title') != payload['title'] or int(ref.get('revision_id') or 0) <= 0:
        raise ValueError('An exact native source revision is required.')
    source = source_record(edition, ref['revision_id'], payload['title'], ref, payload.get('source_page_id'))
    if kind == 'revision':
        parent = payload.get('source_parent') or {}
        if not source.get('parent_id') or int(parent.get('revision_id') or 0) != int(source['parent_id']):
            raise LookupError('The exact native parent is not reconciled. No edit scan was planned.')
        old = source_record(edition, source['parent_id'], payload['title'], parent)
        source.update(parent_wikitext=old['wikitext'], parent_sha256=old['sha256'])
    sources = [source]
    if kind == 'language':
        selected = (payload.get('query') or {}).get('languages', [])
        if not isinstance(selected, list) or not 2 <= len(selected) <= 3 or len(set(selected)) != len(selected) or edition not in selected or not set(selected) <= {'en', 'fi', 'sv'}:
            raise ValueError('Choose two or three editions including this native edition.')
        from core import connect
        from showcase_history import api
        with connect() as db, db.cursor() as c:
            c.execute('SELECT lang,page_id,rev_id,title,date_modified FROM article WHERE wikidata_id=%s', (topic,))
            anchors = {row['lang']: row for row in c.fetchall()}
        for lang in sorted(set(selected) - {edition}):
            anchor = anchors.get(lang)
            if not anchor:
                raise LookupError('A requested edition has no dataset anchor.')
            # Counterparts never outrun the native selected source time or their
            # dataset anchor. Revision IDs come only from the source response.
            cutoff = min(source['timestamp'], anchor['date_modified'])
            answer = api(lang, dict(action='query', prop='revisions', pageids=anchor['page_id'],
                                    rvstart=cutoff, rvdir='older', rvlimit=1, rvprop='ids|timestamp'))
            pages = answer['query']['pages']
            page = pages[0] if isinstance(pages, list) else next(iter(pages.values()))
            if int(page.get('pageid') or 0) != int(anchor['page_id']):
                raise LookupError('The counterpart source page could not be verified.')
            revisions = page.get('revisions') or []
            if len(revisions) != 1 or revisions[0]['timestamp'] > cutoff:
                raise LookupError('An exact historical counterpart is unavailable; no current snapshot was substituted.')
            other = source_record(lang, revisions[0]['revid'], anchor['title'], page_id=anchor['page_id'])
            if other['timestamp'] != revisions[0]['timestamp']:
                raise LookupError('Counterpart metadata changed during preparation.')
            sources.append(other)
    p = jobs.policy()
    config = dict(version='native-on-demand-v1', kind=kind, topic=topic,
                  engine=p['engines'].get(kind, {}).get('configuration', {}),
                  implementation=implementation_identity(), authorization=jobs.digest(p),
                  policy_version=p.get('policy_version', 'unconfigured'))
    return jobs.save_plan(payload['wiki'], config, sorted(sources, key=lambda s: s['lang']))


def dispatch(payload, topic):
    op = payload['op']
    scope = payload['wiki']
    query = payload.get('query') or {}
    if op == 'jobpolicy':
        return describe(topic)
    if op == 'jobs':
        return dict(jobs=jobs.recent(scope, topic))
    if op == 'job':
        return dict(job=jobs.get(query.get('job'), scope, topic))
    # This module is reachable only through the signed native bridge; PHP checks
    # native scan rights, read-only mode and CSRF before supplying this account.
    if int(payload.get('reviewer_id') or 0) <= 0:
        raise ValueError('An authenticated native scan requester is required.')
    if op == 'jobplan':
        return dict(plan=prepare(payload, topic))
    if op == 'enqueue':
        return dict(job=jobs.enqueue(query.get('plan'), scope, topic, int(payload['reviewer_id']), query.get('previous')))
    raise ValueError('Unsupported job operation.')

"""Native wiki bridge and read-only histogram adapters; no preparation on reads.

This module is independent of a Flask application. A wiki authenticates bridge
requests server-to-server; browsers never receive the bridge secret.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

from core import connect
import issues

DETECTOR_KINDS = {
    'FACT': 'Fact', 'FRAMING': 'Wording', 'MOTIVE': 'Motive',
    'REMOVED_CONTEXT': 'Removed context', 'HIDDEN_TEXT': 'Hidden text',
    'CITATION_DATE': 'Citation date', 'CITED_PAGE': 'Cited page',
    'CHERRY_PICK': 'Selective quote', 'OUT_OF_SYNC': 'Out of sync',
}
LABELS = {**issues.KINDS, **DETECTOR_KINDS}


def archived_scan(topic, edition, revision, mode):
    """Successful immutable evidence survives loss of a working JSON cache."""
    with connect() as db,db.cursor() as c:
        c.execute('SELECT payload FROM unified_assessment WHERE topic=%s AND mode=%s ORDER BY assessed_at DESC,id DESC',(topic,mode))
        for row in c.fetchall():
            payload=json.loads(row['payload']);ref=payload.get('ref',{})
            if ref.get('lang')==edition and int(ref.get('revision_id') or 0)==revision:
                return payload['result']
    return None


class Arguments(dict):
    def getlist(self, key):
        value = super().get(key, [])
        return value if isinstance(value, list) else [value]

    def get(self, key, default=None):
        value = super().get(key, default)
        return value[0] if isinstance(value, list) and value else value


def authenticated(body, timestamp, signature, secret, current=None):
    try:
        if abs((time.time() if current is None else current) - int(timestamp)) > 60:
            return False
    except (ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode(), str(timestamp).encode()+b'\n'+body, hashlib.sha256).hexdigest()
    return len(secret) >= 32 and hmac.compare_digest(expected, str(signature))


def article_topic(title, edition, source_page_id=None):
    if edition not in ('en', 'fi', 'sv', 'ru'):
        raise ValueError('Unsupported wiki edition.')
    with connect() as db, db.cursor() as c:
        c.execute('SELECT wikidata_id,page_id FROM article WHERE lang=%s AND title=%s', (edition, title.replace('_', ' ')))
        rows = c.fetchall()
    if len(rows) != 1:
        raise LookupError('This local article has no unique source article identity.')
    if source_page_id is not None and int(rows[0]['page_id']) != int(source_page_id):
        raise LookupError('The imported source page and research article identities do not match.')
    return rows[0]['wikidata_id']


def native_url(topic, edition, params):
    """Only configured native installations; never guess source IDs as oldid."""
    bases = json.loads(os.environ.get('PALIMPSEST_NATIVE_WIKIS', '{}'))
    base = bases.get(edition)
    if not base:
        return None
    manifest_path=os.environ.get('PALIMPSEST_NATIVE_AVAILABILITY_FILE')
    reconciled=None
    if manifest_path:
        try:
            manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
            reconciled=manifest.get('editions',{}).get(edition,{}).get(topic) if manifest.get('version')==1 else None
        except (OSError,ValueError):return None
        if not reconciled:return None
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Native wiki address is invalid.')
    with connect() as db, db.cursor() as c:
        c.execute('SELECT title,page_id FROM article WHERE wikidata_id=%s AND lang=%s', (topic, edition))
        row = c.fetchone()
    if not row:
        return None
    if reconciled and (reconciled.get('title')!=row['title'] or int(reconciled.get('source_page_id',0))!=int(row['page_id'])):
        return None
    return base+'?'+urlencode([('title', row['title']), ('action', 'issues'),
        *((key+'[]' if key in ('languages','kinds') else key,value) for key,value in params)])


def detector_catalog(topic, languages):
    """All successful immutable detector observations, including repeated scans.

    Bucket on SOURCE EDIT time. Assessment times remain separate metadata.
    Missing timestamps remain undated; failed/empty coverage is not a finding.
    """
    with connect() as db, db.cursor() as c:
        c.execute('''SELECT i.id,i.title,o.id observation,o.kind,o.stamp,o.languages,
            o.assessment_id,a.assessed_at,a.mode FROM unified_issue i
            JOIN unified_observation o ON o.issue_id=i.id
            JOIN unified_assessment a ON a.id=o.assessment_id
            WHERE i.topic=%s AND i.origin='flags' ORDER BY o.stamp,o.id''', (topic,))
        found = list(c.fetchall())
        c.execute("SELECT scope,state,assessed_at,note FROM unified_coverage WHERE topic=%s AND origin='flags'", (topic,))
        coverage = list(c.fetchall())
        c.execute("SELECT id,payload,assessed_at,mode FROM unified_assessment WHERE topic=%s AND mode IN ('revision','page')", (topic,))
        assessments = list(c.fetchall())
    source_times={}
    successes=[]
    for assessment in assessments:
        payload=json.loads(assessment['payload']);ref=payload.get('ref',{});result=payload.get('result',{})
        if ref.get('lang') not in languages:continue
        source_times[(ref.get('lang'),ref.get('revision_id'))]=ref.get('timestamp','')
        successes.append(dict(assessment=assessment['id'],source_stamp=ref.get('timestamp',''),
            lang=ref.get('lang'),revision=ref.get('revision_id'),mode=assessment['mode'],
            assessed_at=assessment['assessed_at'],state='partial' if result.get('partial') else 'completed',
            empty=not bool(result.get('flags'))))
    groups = {}
    undated = 0
    for row in found:
        editions = row['languages'].split(',')
        if not set(editions) <= set(languages):
            continue
        if not row['stamp']:
            undated += 1
            continue
        group = groups.setdefault(row['id'], dict(id='flags:'+row['id'], issue=row['id'],
            title=row['title'], origin='flags', title_status='source', cells=[]))
        group['cells'].append(dict(stamp=row['stamp'], kind=row['kind'], observation=row['observation'],
            assessment=row['assessment_id'], assessed_at=row['assessed_at'], mode=row['mode'],
            pair_kinds=[dict(pair='–'.join(x.upper() for x in editions), kind=row['kind'])]))
    selected_coverage=[]
    for row in coverage:
        row['scope']=json.loads(row['scope'])
        if row['scope'].get('lang') in languages:
            row['source_stamp']=source_times.get((row['scope'].get('lang'),row['scope'].get('revision')),'')
            if not row['source_stamp']:
                from revision_text import cached_revision
                record=cached_revision(row['scope'].get('lang'),row['scope'].get('revision')) or {}
                row['source_stamp']=record.get('timestamp','')
            selected_coverage.append(row)
    return dict(rows=list(groups.values()), coverage=selected_coverage, assessments=successes, undated=undated,
        time_axis='source_edit', notice='Detector buckets use source edit time, not scan time. Scans are sparse and on demand; no continuous coverage is implied.')


def dispatch(payload):
    """Called only after signature verification. All read operations are explicit."""
    edition = payload.get('edition', '')
    topic = article_topic(payload.get('title', ''), edition, payload.get('source_page_id'))
    args = Arguments(payload.get('query') or {})
    args['lang'] = edition
    wiki=payload.get('wiki','')
    if not isinstance(wiki,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',wiki):
        raise ValueError('A native wiki identity is required.')
    op = payload.get('op', 'list')
    if op in ('jobpolicy','jobplan','enqueue','jobs','job'):
        from on_demand_bridge import dispatch as job_dispatch
        return job_dispatch(payload,topic)
    if op=='scan' and os.environ.get('NEOWIKI_ON_DEMAND_ROOT'):
        raise ValueError('Use the authenticated background request preview and queue. Synchronous paid scans are disabled.')
    if op == 'list':
        result = issues.list_issues(topic, args, review_scope=wiki)
        result.update(topic=topic, labels=LABELS)
        return result
    if op == 'legacy':
        iid, row = issues.resolve_legacy(topic, args)
        return dict(issue=iid, observation=row['id'], occurrence=row['occurrence'])
    if op == 'detail':
        row = issues.get_observation(topic, args.get('issue'), args.get('observation'), args.get('occurrence'), edition,review_scope=wiki)
        selected = args.getlist('languages')
        if selected and not set(row['languages']) <= set(selected):
            raise LookupError('This exact occurrence does not match the selected editions.')
        if args.get('kind') and row['kind'] != args.get('kind'):
            raise LookupError('The exact occurrence does not support the selected classification.')
        if row['mode']=='language' and args.get('run') and row['context']['run']!=args['run']:
            raise LookupError('The exact observation belongs to a different analysis run.')
        from issue_evidence import evidence_view
        view = evidence_view(row, edition, args.get('expanded') == '1')
        for source in view['sources']:
            public=urlsplit(source['url']);language=public.hostname.split('.')[0]
            revision=parse_qs(public.query).get('oldid',[''])[0]
            if language!=edition and revision.isdigit():
                source['native_url']=native_url(topic,language,[('source',revision),*((key,value) for key,values in args.items() for value in (values if isinstance(values,list) else [values]) if key not in ('source','lang'))])
                if source['native_url']:source['native_other_wiki']=language.upper()
        return dict(issue=row, evidence=view, topic=topic)
    if op == 'translate':
        row=issues.get_observation(topic,args.get('issue'),args.get('observation'),args.get('occurrence'),edition,review_scope=wiki)
        from issue_context import translate_source
        try:return translate_source(row,args.get('translation_source'))
        except RuntimeError:raise LookupError('The local English translator is unavailable on this server. Original passages are preserved; retry when its language model is installed.') from None
    if op == 'review':
        oid=args.get('observation');iid=args.get('issue')
        if not oid or not iid or not isinstance(payload.get('reviewed'),bool) or int(payload.get('reviewer_id') or 0)<=0:
            raise ValueError('An authenticated account and exact observation are required.')
        row=issues.get_observation(topic,iid,oid,edition=edition,review_scope=wiki)
        reviewed=payload['reviewed']
        with connect() as db,db.cursor() as c:
            c.execute('''INSERT INTO unified_native_review(wiki,observation_id,edition,reviewed,reviewer_id)
                VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE reviewed=VALUES(reviewed),reviewer_id=VALUES(reviewer_id)''',
                (wiki,row['observation'],edition,reviewed,int(payload['reviewer_id'])))
        return dict(reviewed=reviewed,edition=edition,observation=oid)
    if op == 'health':
        from flags_routes import requests
        try:
            response=requests.get(os.environ.get('PALIMPSEST_API_URL','http://127.0.0.1:8765').rstrip('/')+'/healthz',timeout=3)
            response.raise_for_status()
            configured=response.json().get('judge_configured') is True
            allowed=os.environ.get('PALIMPSEST_ISSUES_VERIFY_CACHED_ONLY')!='1'
            return dict(available=True,configured=configured,new_inference_allowed=allowed,
                message=('Detector ready. Scans run only when requested.' if allowed else 'Cached-only native verification: new inference is disabled.') if configured else 'Detector is not configured.')
        except Exception:
            return dict(available=False,configured=False,message='Detector unavailable. Cached evidence remains readable.')
    if op in ('scan', 'cached'):
        # The native server has verified its reconciliation manifest and readable
        # local revision. Verify the source text too before using a source audit.
        from revision_text import cached_revision, fetch_revision
        from flags_tab import RevisionRef
        from flags_routes import response_payload, page_response_payload, cached_audit, cached_page_audit, pending_result
        ref = payload.get('source') or {}
        rid = int(ref.get('revision_id') or 0)
        if rid <= 0 or ref.get('lang') != edition or ref.get('title') != payload['title']:
            raise ValueError('The selected source identity is invalid.')
        mode=payload.get('mode','revision')
        if mode not in ('revision','page'):raise ValueError('Choose revision or page consistency.')
        selected=RevisionRef(edition,rid,payload['title'],ref.get('timestamp',''),'',ref.get('parent_id'))
        context=dict(topic=topic)
        archived=archived_scan(topic,edition,rid,mode)
        if archived:
            # Normal explicit scans reuse saved assessments. Only an explicit
            # fresh request may bypass one; historical browsing never does.
            context['page_audits' if mode=='page' else 'audits']={str(rid):archived}
        pending=pending_result(selected,context,mode) if op=='scan' else None
        working=cached_page_audit(selected,context) if mode=='page' else cached_audit(selected,context)
        if op=='scan' and os.environ.get('PALIMPSEST_ISSUES_VERIFY_CACHED_ONLY')=='1' and (payload.get('fresh') is True or not (pending or archived or working)):
            raise LookupError('New inference is disabled during native verification. Previously saved evidence remains readable.')
        source=cached_revision(edition,rid)
        if not source:
            # Archived successful text/pending storage recovery remains readable
            # even when the separate revision download cache is unavailable.
            saved=pending or archived or working
            text=saved.get('wikitext' if mode=='page' else 'new_wikitext') if saved else None
            if text is not None:source=dict(wikitext=text,timestamp=ref.get('timestamp',''),parent_id=ref.get('parent_id'))
        if not source and op=='scan':source=fetch_revision(edition,rid)
        if not source:
            raise LookupError('Source text is unavailable locally. No scan was started.')
        if hashlib.sha256(source['wikitext'].encode()).hexdigest() != ref.get('sha256'):
            raise LookupError('Local and source revision text differ. No source audit was substituted.')
        selected=RevisionRef(edition,rid,payload['title'],source.get('timestamp',''),'',source.get('parent_id'))
        fn=page_response_payload if mode=='page' else response_payload
        if payload.get('fresh') is True:
            context.pop('audits',None);context.pop('page_audits',None)
        if mode == 'page':
            return fn(selected,context,op=='scan',payload.get('fresh') is True,render_page=False)
        return fn(selected,context,op=='scan',payload.get('fresh') is True)
    raise ValueError('Unsupported native Issues operation.')

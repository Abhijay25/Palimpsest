"""First-level discrepancy lifetime viewer. Reads cached engine outputs; never spends.

Illustrative intervals are isolated from both the real showcase and edit timeline.
The existing engine yields snapshot findings, not verified lifetime histories.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets

from flask import Blueprint, jsonify, render_template, request,session

bp = Blueprint('discrepancy_explorer', __name__)


def skyline_run():
    from skyline import selection
    from paired_history import summary
    topic,languages,run=selection(request.args)
    result=summary(topic,languages,run=run) if run else summary(topic,languages)
    if result is None:raise LookupError('This language comparison is not prepared yet. No inference was started by opening this page.')
    return result,languages


@bp.get('/explore/api/skyline')
def skyline_overview():
    from skyline import aggregate
    try:
        data,languages=skyline_run()
        return jsonify(aggregate(data,languages))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404
    except Exception:return jsonify(error='The comparison database is unavailable. Retry when it is ready.'),503


@bp.get('/explore/api/questions')
def skyline_questions():
    from skyline import question_page
    try:
        data,languages=skyline_run()
        return jsonify(question_page(data,languages,request.args.get('stamp',''),int(request.args.get('page','1')),
                        request.args.get('kind','all'),request.args.get('current','en'),request.args.get('back','')))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404
    except Exception:return jsonify(error='Stored question evidence is temporarily unavailable.'),503


@bp.get('/explore/api/matrix')
def heatmap_matrix():
    from heatmap import public_catalog
    try:
        data,languages=skyline_run()
        return jsonify(public_catalog(data,languages))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404
    except Exception:return jsonify(error='Stored question matrix is temporarily unavailable.'),503


@bp.get('/explore/api/cell')
def heatmap_cell():
    from heatmap import cell_detail
    try:
        if not detail_args(request.args):raise ValueError('Invalid historical cell identity.')
        if len(request.args.get('back',''))>2500:raise ValueError('Invalid return context.')
        data,languages=skyline_run()
        return jsonify(cell_detail(data,languages,request.args['group'],request.args['stamp'],request.args.get('current','en'),request.args.get('back',''),request.args.get('pair','all'),request.args.get('kind','all')))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404
    except Exception:return jsonify(error='Stored cell evidence is temporarily unavailable.'),503


@bp.post('/explore/api/search')
def heatmap_search():
    if request.headers.get('Sec-Fetch-Site')=='cross-site' or not secrets.compare_digest(request.headers.get('X-Review-Token',''),session.get('review_token','invalid')):
        return jsonify(error='Reload this local page before searching.'),403
    from heatmap import catalog,hybrid_search
    try:
        data,languages=skyline_run()
        query=(request.get_json(silent=True) or {}).get('query','')
        if not isinstance(query,str):raise ValueError('Enter a search phrase.')
        return jsonify(hybrid_search(catalog(data,languages)['rows'],query))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404
    except Exception:return jsonify(error='Search is temporarily unavailable. Clear the search to explore all questions.'),503


@bp.get('/explore/api/history')
def historical():
    topic=request.args.get('topic','')
    languages=list(dict.fromkeys(request.args.getlist('languages') or ['en','fi','ru']))
    if not re.fullmatch(r'Q\d{1,15}',topic) or not 2<=len(languages)<=4 or not set(languages)<={'en','fi','sv','ru'}:
        return jsonify(error='Choose a valid topic and two to four supported editions.'),400
    try:
        from paired_history import summary
        result=summary(topic,languages)
        if result is None:
            return jsonify(error='A historical replay is not prepared for this topic/language set. Cached snapshots remain available separately.'),404
        return jsonify(result)
    except Exception:
        return jsonify(error='Historical comparisons are unavailable while the local database or preparation is offline. No inference was started.'),503


@bp.get('/explore')
def page():
    session.setdefault('review_token',secrets.token_hex(24))
    return render_template('discrepancy_explorer.html')


def detail_args(data):
    run=data.get('run','');group=data.get('group','');stamp=data.get('stamp','')
    if not re.fullmatch(r'[a-f0-9]{64}',run) or not re.fullmatch(r'[a-f0-9]{64}',group) or not re.fullmatch(r'[0-9TZ:+.\-]{10,35}',stamp):
        return None
    return run,group,stamp


@bp.get('/explore/api/details')
def historical_detail():
    args=detail_args(request.args)
    if not args:return jsonify(error='Invalid historical occurrence identity.'),400
    languages=request.args.getlist('languages') or None
    if languages and (not 2<=len(set(languages))<=4 or not set(languages)<={'en','fi','sv','ru'}):return jsonify(error='Choose two to four supported editions.'),400
    from paired_history import detail
    result=detail(*args,languages=languages)
    return (jsonify(result),200) if result else (jsonify(error='Source occurrences are not available yet.'),404)


@bp.post('/explore/api/enrich')
def enrich():
    if request.headers.get('Sec-Fetch-Site')=='cross-site' or not secrets.compare_digest(request.headers.get('X-Review-Token',''),session.get('review_token','invalid')):
        return jsonify(error='Reload this local page before requesting evidence enrichment.'),403
    data=request.get_json(silent=True) or {};args=detail_args(data)
    if not args:return jsonify(error='Invalid historical occurrence identity.'),400
    from paired_history import detail
    result=detail(*args)
    if not result:return jsonify(error='Source occurrences are unavailable.'),404
    occurrence=next((o for o in result['occurrences'] if o['id']==data.get('occurrence')),None)
    if not occurrence:return jsonify(error='Select a stored source occurrence.'),400
    try:
        from local_translation import translate,init
        init()
        for e in occurrence['evidence']:
            if e['lang']!='en' and not e.get('translation'):e['translation']=translate(e['quote'],e['lang'])['text']
        if occurrence['kind']=='contradiction' and not occurrence.get('highlighted'):
            from historical_divergence import highlights
            selected={e['lang']:e for e in occurrence['evidence']};key='_'.join(selected)
            highlights(selected,{key:dict(kind='contradiction')});occurrence['highlighted']=True
        from core import connect
        payload={k:v for k,v in occurrence.items() if k!='id'}
        with connect() as db,db.cursor() as c:c.execute('UPDATE paired_occurrence SET payload=%s WHERE id=%s',(json.dumps(payload,ensure_ascii=False),occurrence['id']))
        return jsonify(occurrence)
    except Exception:
        return jsonify(error='Enrichment is unavailable. Original revision evidence remains visible.'),503


def snapshot_rows(findings, observed, languages):
    """Preserve exact evidence and uncertainty. Do not infer starts, ends or clusters."""
    rows = []
    for finding in findings:
        if finding.get('category') not in ('conflict', 'coverage', 'framing'):
            continue
        evidence = [e for e in finding.get('evidence', []) if e.get('lang') in languages]
        if len({e['lang'] for e in evidence}) < 2:
            continue
        kind = {'conflict': 'contradiction', 'coverage': 'omission', 'framing': 'framing'}.get(finding.get('category'), 'uncertain')
        def convert(e):
            return dict(lang=e['lang'], quote=e.get('quote', ''), translation=e.get('translation') or '',
                        highlights=e.get('highlights', []), mark=e.get('highlight', ''),
                        url=f"https://{e['lang']}.wikipedia.org/w/index.php?oldid={int(e['rev_id'])}" if e.get('rev_id') else None,
                        revision=e.get('rev_id'), section=e.get('section', 'Selected passage'))
        identity = str(finding.get('id') or hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest())
        rows.append(dict(id=identity, title=finding.get('title', 'Finding awaiting a claim group'),
                         section=evidence[0].get('section', 'Selected passage'),
                         languages=list(dict.fromkeys(e['lang'] for e in evidence)), grouped=False,
                         phases=[dict(id=identity + '-snapshot', start=observed, end=observed,
                             kind=kind, snapshot=True, reason=finding.get('reasoning') or finding.get('summary', ''),
                             action=finding.get('action', 'Verify both source revisions and their cited sources.'),
                             evidence=[convert(e) for e in evidence])]))
    return rows


@bp.get('/explore/api/cached')
def cached():
    topic = request.args.get('topic', '')
    if not re.fullmatch(r'Q\d{1,15}', topic):
        return jsonify(error='Choose a Wikipedia topic with a valid Wikidata ID.'), 400
    # No imports that fetch models or perform provider calls. This endpoint reads only.
    try:
        from core import connect
        with connect() as db, db.cursor() as cursor:
            db._read_timeout = 8
            cursor.execute('SELECT * FROM review_run WHERE topic=%s ORDER BY created DESC LIMIT 1', (topic,))
            run = cursor.fetchone()
            if not run:
                return jsonify(error='No cached engine analysis exists for this topic. Use the illustrative viewer or prepare a comparison in the existing tracker.'), 404
            cursor.execute("SELECT findings FROM review_group WHERE run_id=%s AND status='done'", (run['id'],))
            findings = [f for row in cursor.fetchall() for f in json.loads(row['findings'])]
            cursor.execute('SELECT lang,title,date_modified FROM article WHERE wikidata_id=%s', (topic,))
            articles = cursor.fetchall()
        observed = run.get('created') or run.get('updated')
        if isinstance(observed, datetime):
            observed = observed.replace(tzinfo=timezone.utc).isoformat()
        if not observed:
            return jsonify(error='This run has no observation timestamp, so it cannot be placed on a timeline.'), 409
        seen = set()
        unique = []
        for finding in findings:
            key = json.dumps([finding.get('category'), sorted((e.get('lang'), e.get('quote')) for e in finding.get('evidence', []))], sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(finding)
        languages = [a['lang'] for a in articles]
        title = next((a['title'] for a in articles if a['lang'] == 'en'), articles[0]['title'] if articles else topic)
        return jsonify(topic=dict(id=topic, title=title, languages=languages, description='Cached engine observations'),
                       mode='cached', asOf=str(observed), rows=snapshot_rows(unique, str(observed), languages),
                       warning='Real cached findings, shown at their analysis timestamp. Start dates, resolution dates and shared claim groups are unknown. A point is an observation, not a lifetime.')
    except Exception:
        return jsonify(error='The local comparison database is unavailable. The illustrative viewer still works; retry cached results when MariaDB is ready.'), 503

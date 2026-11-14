"""Read-only timeline pages; explicit CSRF-protected historical retrieval."""
import difflib
import secrets
from html import escape
import pymysql
import requests
from flask import Blueprint, abort, render_template, request, session
from markupsafe import Markup
import semantic_timeline as timeline

bp = Blueprint('timeline', __name__)


def current_language():
    lang=request.args.get('lang','en')
    if lang not in timeline.LANGUAGES:
        abort(400)
    return lang


def validate_topic(topic):
    if topic != timeline.TOPIC:
        abort(404)


def marked_diff(before,after):
    """Escape source before adding our own inline diff markup."""
    old=[];new=[]
    for tag,a,b,x,y in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
        left=escape(before[a:b]);right=escape(after[x:y])
        old.append('<del>'+left+'</del>' if tag in ('delete','replace') else left)
        new.append('<ins>'+right+'</ins>' if tag in ('insert','replace') else right)
    return Markup(''.join(old)),Markup(''.join(new))


def detail_context(event,lang,counterparts=None,error=None):
    for unit in event['units']:
        unit['old_html'],unit['new_html']=marked_diff(unit['data']['before'],unit['data']['after'])
    matches={m['unit_id']:m['candidates'] for m in (counterparts or {}).get('matches',[])}
    return dict(topic=timeline.TOPIC,event=event,lang=lang,languages=timeline.LANGUAGES,
                categories=timeline.CATEGORIES,counterparts=counterparts,matches=matches,error=error,
                original_before=timeline.cached_revision(event['lang'],event['before_rev']),
                original_after=timeline.cached_revision(event['lang'],event['after_rev']))


@bp.get('/wiki/<topic>/timeline')
def page(topic):
    validate_topic(topic);lang=current_language()
    try:
        events,status=timeline.overview();anchors=timeline.editions()
    except pymysql.err.ProgrammingError as error:
        if error.args[0] != 1146:
            raise
        events=[];anchors={};status=None
    selected=next((e for e in events if e['id']==request.args.get('event')),None)
    compact=[{k:e[k] for k in ('id','lang','stamp','title','categories','before_rev','after_rev','summary')} for e in events]
    return render_template('timeline.html',topic=topic,lang=lang,languages=timeline.LANGUAGES,
        categories=timeline.CATEGORIES,events=events,status=status,anchors=anchors,chart_events=compact,
        selected_context=detail_context(selected,lang) if selected else None)


@bp.get('/wiki/<topic>/timeline/events/<identity>')
def detail(topic,identity):
    validate_topic(topic);lang=current_language();event=timeline.event_detail(identity)
    if not event:
        abort(404)
    return render_template('timeline_event.html',**detail_context(event,lang))


@bp.post('/wiki/<topic>/timeline/events/<identity>/compare')
def compare(topic,identity):
    validate_topic(topic);lang=current_language()
    if request.headers.get('Sec-Fetch-Site')=='cross-site' or not secrets.compare_digest(
            request.form.get('token',''),session.get('review_token','invalid')):
        abort(403)
    event=timeline.event_detail(identity)
    if not event:
        abort(404)
    try:
        result=timeline.compare_at_time(identity,lang)
        return render_template('timeline_event.html',**detail_context(event,lang,result))
    except (requests.RequestException,ValueError,RuntimeError) as error:
        return render_template('timeline_event.html',**detail_context(event,lang,error=
            'Historical retrieval is unavailable. Exact revision evidence is preserved; retry when the local model and network are available.')),503

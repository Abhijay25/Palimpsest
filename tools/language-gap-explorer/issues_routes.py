"""Article Issues UI and read-only evidence APIs; protected review markers."""
import difflib
import html
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit
from flask import Blueprint,abort,jsonify,redirect,render_template,request,session
from markupsafe import Markup
import issues
from core import connect

bp=Blueprint('issues',__name__)

def validate_topic(topic):
    if not re.fullmatch(r'Q\d{1,15}',topic):abort(404)

def context(topic):
    validate_topic(topic)
    with connect() as db,db.cursor() as c:
        c.execute('SELECT lang,title FROM article WHERE wikidata_id=%s',(topic,));articles=list(c.fetchall())
        if not articles:
            c.execute('SELECT title FROM unified_issue WHERE topic=%s LIMIT 1',(topic,));stored=c.fetchone()
            if not stored:abort(404)
        title=next((a['title'] for a in articles if a['lang']=='en'),articles[0]['title'] if articles else topic)
    edition=request.args.get('lang','en')
    if not re.fullmatch(r'[a-z][a-z-]{1,11}',edition):abort(400)
    return dict(topic=topic,title=title,current_lang=edition,active_article_tab='issues',issue_workspace=True)

def target(topic,iid,oid,occurrence=None,args=None):
    query=(args or request.args).copy();query.poplist('tab');query.poplist('scan');query.poplist('tools')
    query.setlist('observation',[oid])
    if occurrence:query.setlist('occurrence',[occurrence])
    else:query.poplist('occurrence')
    return '/article/'+topic+'/issues/'+iid+'?'+urlencode(list(query.items(multi=True)))

def safe_back(topic):
    back=request.args.get('back','')
    if back and len(back)<=4000:
        parsed=urlsplit(back)
        if not parsed.scheme and not parsed.netloc and parsed.path=='/article/'+topic+'/issues':return back
    skyline=request.args.get('skyline','')
    if skyline and len(skyline)<=2500:return '/explore?'+skyline
    return '/article/'+topic+'/issues?'+urlencode({'lang':request.args.get('lang','en')})

def legacy(topic):
    validate_topic(topic)
    try:
        from skyline import selection
        from paired_history import summary
        args=request.args.copy();args['topic']=topic
        selected,languages,run=selection(args)
        if not run or not summary(topic,languages,run=run):raise LookupError('This historical comparison is unavailable. No snapshot was substituted.')
        iid,row=issues.resolve_legacy(topic,request.args)
        return redirect(target(topic,iid,row['id'],row['occurrence']),302)
    except (ValueError,LookupError) as error:return unavailable(topic,error)

def unavailable(topic,error,code=None):
    return render_template('issue_unavailable.html',topic=topic,title='Issue evidence unavailable',current_lang=request.args.get('lang','en'),message=str(error),active_article_tab='issues'),code or (400 if isinstance(error,ValueError) else 404)

@bp.get('/article/<topic>/issues')
def index(topic):
    ctx=context(topic)
    try:data=issues.list_issues(topic,request.args)
    except (ValueError,LookupError) as error:return unavailable(topic,error)
    query=request.args.copy();query.poplist('page')
    data['query']=list(query.items(multi=True));back=request.full_path.rstrip('?')
    for row in data['issues']:
        args=request.args.copy();args.setlist('back',[back]);args.setlist('lang',[ctx['current_lang']])
        row['href']=target(topic,row['id'],row['observation'],row['occurrence'],args)
    return render_template('issues.html',**ctx,**data)

@bp.get('/article/<topic>/issues/checks')
def checks(topic):
    validate_topic(topic)
    query=request.args.copy();query['tab']='flags';query['tools']='1';query.poplist('scan')
    return redirect('/article/'+topic+'?'+urlencode(list(query.items(multi=True))))

@bp.get('/api/issues')
def list_api():
    topic=request.args.get('topic','');validate_topic(topic)
    try:return jsonify(issues.list_issues(topic,request.args))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404

@bp.get('/api/issues/native-target')
def native_target():
    """Exact histogram handoff; returns preview only when native is unconfigured."""
    from native_issues import native_url
    topic=request.args.get('topic','');validate_topic(topic)
    edition=request.args.get('lang',request.args.get('current','en'))
    try:
        if request.args.get('issue'):
            row=issues.get_observation(topic,request.args['issue'],request.args.get('observation'),request.args.get('occurrence'),edition)
            iid=row['id'];oid=row['observation'];occurrence=row['occurrence']
        else:
            iid,row=issues.resolve_legacy(topic,request.args);oid=row['id'];occurrence=row['occurrence']
        selected=request.args.getlist('languages')
        langs=row['languages'] if isinstance(row['languages'],list) else row['languages'].split(',')
        if selected and not set(langs)<=set(selected):raise LookupError('This exact source does not support the selected editions.')
        if request.args.get('kind') and row['kind']!=request.args['kind']:raise LookupError('This exact occurrence does not support the selected classification.')
        params=[(k,v) for k,v in request.args.items(multi=True) if k not in ('topic','current','issue','observation','occurrence','lang','scan')]
        params.extend([('issue',iid),('observation',oid),('lang',edition)])
        if occurrence:params.append(('occurrence',occurrence))
        native=native_url(topic,edition,params)
        fallback='/article/'+topic+'/issues/'+iid+'?'+urlencode(params)
        return jsonify(href=native or fallback,native=bool(native),issue=iid,observation=oid,occurrence=occurrence)
    except (ValueError,LookupError) as error:return jsonify(error=str(error)),404

from issue_evidence import cropped_diff, comparison_table, evidence_view

@bp.get('/article/<topic>/issues/<iid>')
def detail(topic,iid):
    ctx=context(topic)
    try:
        row=issues.get_observation(topic,iid,request.args.get('observation'),request.args.get('occurrence'),ctx['current_lang'])
        selected=request.args.getlist('languages')
        if selected and not set(row['languages'])<=set(selected):raise LookupError('This occurrence does not match the requested language comparison.')
        view=evidence_view(row,ctx['current_lang'],request.args.get('expanded')=='1')
    except (ValueError,LookupError) as error:return unavailable(topic,error)
    for item in row['observations']:item['href']=target(topic,iid,item['id'],item['occurrence'])
    query=request.args.copy();query.setlist('observation',[row['observation']]);query.setlist('expanded',['0' if request.args.get('expanded')=='1' else '1'])
    return render_template('issue_detail.html',**ctx,issue=row,view=view,back=safe_back(topic),expand_url=request.path+'?'+urlencode(list(query.items(multi=True))))

@bp.get('/api/issues/<iid>')
def detail_api(iid):
    topic=request.args.get('topic','');validate_topic(topic)
    try:
        row=issues.get_observation(topic,iid,request.args.get('observation'),request.args.get('occurrence'),request.args.get('lang','en'))
        selected=request.args.getlist('languages')
        if selected and not set(row['languages'])<=set(selected):raise LookupError('This occurrence does not match the requested editions.')
        view=evidence_view(row,request.args.get('lang','en'),request.args.get('expanded')=='1')
        return jsonify(issue={k:row[k] for k in ('id','topic','title','origin','kind','observation','stamp','assessed_at','languages','occurrence','mode','reviewed','observations')},evidence=view)
    except (ValueError,LookupError) as error:return jsonify(error=str(error)),404

@bp.post('/api/issues/<iid>/review')
def review(iid):
    token=request.headers.get('X-Review-Token','')
    if request.headers.get('Sec-Fetch-Site')=='cross-site' or not token or not secrets.compare_digest(token,session.get('review_token','invalid')):return jsonify(error='Reload this page before updating its review marker.'),403
    body=request.get_json(silent=True) or {};topic=body.get('topic','');validate_topic(topic)
    if not isinstance(body.get('reviewed'),bool):return jsonify(error='Choose reviewed or unreviewed.'),400
    if not body.get('observation'):return jsonify(error='Choose an exact observation.'),400
    try:return jsonify(issues.mark_reviewed(topic,iid,body['observation'],body.get('edition','en'),body['reviewed']))
    except ValueError as error:return jsonify(error=str(error)),400
    except LookupError as error:return jsonify(error=str(error)),404

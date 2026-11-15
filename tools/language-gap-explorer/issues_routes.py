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

def cropped_diff(old,new,flag):
    """Focus a real edit hunk; counterpart ranges come from the same diff opcode."""
    side='old' if flag.get('side')=='old' else 'new';quote=flag.get('anchor_text','')
    lines=[old.splitlines(keepends=True),new.splitlines(keepends=True)]
    text=old if side=='old' else new;position=text.find(quote) if quote else -1
    if position<0:return old,new,False
    line=text[:position].count('\n');column=1 if side=='old' else 3
    groups=list(difflib.SequenceMatcher(None,*lines,autojunk=False).get_grouped_opcodes(3))
    for group in groups:
        if group[0][column]<=line<group[-1][column+1]:
            return ''.join(lines[0][group[0][1]:group[-1][2]]),''.join(lines[1][group[0][3]:group[-1][4]]),True
    return old,new,False

def comparison_table(columns):
    headers=''.join('<th scope="col">'+html.escape(c['label'])+'</th>' for c in columns)
    body=''.join('<td class="mw-diff-inline-'+('deleted' if index==0 else 'added')+'" data-diff-side="'+('old' if index==0 else 'new')+'">'+html.escape(c['text'])+'</td>' for index,c in enumerate(columns))
    return Markup('<table style="grid-template-columns:repeat('+str(len(columns))+',minmax(0,1fr))" class="flags-diff diff mw-diff-inline"><thead><tr>'+headers+'</tr></thead><tbody><tr>'+body+'</tr></tbody></table>')

def evidence_view(row,edition,expanded=False):
    data=row['evidence'];mode=row['mode'];sources=[];annotations=[];notice='';translations=[]
    if mode in ('language','snapshot'):
        evidence=list(data.get('evidence',[]))
        evidence.sort(key=lambda e:e.get('lang')!=edition)
        if len(evidence)<2:raise LookupError('The source comparison is incomplete. No substitute passages were used.')
        columns=[]
        if not any(e.get('lang')==edition for e in evidence):columns.append(dict(label=edition.upper()+' · evidence unavailable',text='This selected edition has no supporting passage in this occurrence.'))
        for e in evidence:
            lang=e['lang'];revision=e.get('revision',e.get('rev_id'))
            if lang not in ('en','fi','sv','ru'):raise LookupError('Unsupported source edition in this observation.')
            if not revision or not str(revision).isdigit() or int(revision)<=0:raise LookupError('A source revision is missing.')
            quote=e.get('quote') or ''
            if not quote:raise LookupError('The exact source excerpt is unavailable.')
            url=f'https://{lang}.wikipedia.org/w/index.php?oldid={revision}'
            if e.get('url') and e['url']!=url:raise LookupError('The archived revision URL is inconsistent.')
            if row['stamp'] and e.get('stamp','')>row['stamp']:raise LookupError('The source revision exceeds the observation date.')
            columns.append(dict(label=lang.upper()+' · revision '+str(revision),text=quote))
            sources.append(dict(label=lang.upper()+' · '+str(revision),url=url,stamp=e.get('stamp','')))
            translated=e.get('translation')
            if not translated and lang!='en':
                try:
                    with connect() as db,db.cursor() as c:
                        c.execute('SELECT translated FROM local_translation WHERE lang=%s AND source=%s ORDER BY created DESC LIMIT 1',(lang,quote));cached=c.fetchone()
                    translated=cached['translated'] if cached else None
                except Exception:translated=None
            if isinstance(translated,str) and translated:translations.append(dict(lang=lang,text=translated))
            spans=e.get('highlights') or []
            anchor=quote
            if spans:
                start,end=spans[0].get('start'),spans[0].get('end')
                if isinstance(start,int) and isinstance(end,int) and 0<=start<end<=len(quote):anchor=quote[start:end]
            annotations.append(dict(id=row['id']+'-'+str(len(columns)),kind=row['kind'],tier='review',title=row['title'],reason=data.get('reason') or 'Stored language comparison: '+row['label']+'. This annotation identifies the assessed passage; it does not establish which account is correct.',anchor_text=anchor,side='old' if len(columns)==1 else 'new',evidence=[]))
        notice='Snapshot-only comparison; historical lifetime is unknown.' if mode=='snapshot' else 'Exact archived source passages. Observations do not establish continuous persistence or a current error.'
        return dict(diff_html=comparison_table(columns),flags=annotations,sources=sources,notice=notice,focused=True,translations=translations,mode_label='Language editions')
    result=data['result'];ref=data['ref'];flag=row['context']['flag'];annotations=[flag]
    if ref.get('lang') not in ('en','fi','sv','ru') or int(ref.get('revision_id') or 0)<=0:raise LookupError('The exact assessed source revision is unavailable.')
    sources=[dict(label=ref['lang'].upper()+' · '+str(ref['revision_id']),url=f"https://{ref['lang']}.wikipedia.org/w/index.php?oldid={ref['revision_id']}",stamp=ref.get('timestamp',''))]
    if mode=='revision':
        old=result.get('old_wikitext');new=result.get('new_wikitext')
        if old is None or new is None:raise LookupError('This audit has no preserved revision text.')
        if ref.get('parent_id'):sources.insert(0,dict(label='Parent · '+str(ref['parent_id']),url=f"https://{ref['lang']}.wikipedia.org/w/index.php?oldid={ref['parent_id']}",stamp=''))
        focused=False
        if not expanded:old,new,focused=cropped_diff(old,new,flag)
        from flags_routes import diff_html
        return dict(diff_html=Markup(diff_html(old,new)),flags=annotations,sources=sources,notice='Parent versus selected revision. Detector suggestions require review.',focused=focused,translations=[],mode_label='Revision edit')
    text=result.get('wikitext')
    if not text:raise LookupError('The assessed page text is unavailable.')
    first=flag.get('context_sentence') or flag.get('anchor_text','');second=next((e.get('quote') for e in flag.get('evidence',[]) if e.get('source')=='page' and e.get('quote')!=first),'')
    if expanded:columns=[dict(label='Assessed revision · full text',text=text)]
    else:columns=[dict(label='First passage · same revision',text=first if first and first in text else 'Exact passage anchor unavailable.'),dict(label='Related passage · same revision',text=second if second and second in text else 'Exact related passage anchor unavailable.')]
    annotations=[dict(flag,side='old',anchor_text=first if first in text else '')]
    if second and second in text:annotations.append(dict(flag,id=str(flag.get('id'))+'-related',side='new',anchor_text=second,title='Related passage: '+flag.get('title','Internal inconsistency')))
    return dict(diff_html=comparison_table(columns),flags=annotations,sources=sources,notice='Two statements from the same revision, not an edit or a comparison of editions.',focused=not expanded,translations=[],mode_label='Within one revision')

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

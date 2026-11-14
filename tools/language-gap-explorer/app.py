import json
import re
import secrets
from datetime import datetime, timezone
try:
    import pymysql
    _MYSQL_AVAILABLE=True
except ModuleNotFoundError:  # permits the explicit offline fixture without DB extras
    _MYSQL_AVAILABLE=False
    class pymysql:  # type: ignore[no-redef]
        class MySQLError(Exception): pass
try:
    import requests
except ModuleNotFoundError:
    requests=None
from flask import Flask, render_template, request, abort, jsonify, redirect, url_for, session
if _MYSQL_AVAILABLE:
    from core import connect, compare, LANGS, MODEL
else:
    LANGS=('fi','en','sv');MODEL='offline'
    def connect(): raise pymysql.MySQLError('MariaDB support is not installed.')
    def compare(*_args): return []


def comparison_context(topic):
    """Existing comparison preparation, kept separate so article tabs reuse it."""
    source=request.args.get('lang') or request.args.get('source') or session.get('showcase_article_language','en' if topic=='Q2606233' else 'fi')
    target=request.args.get('target') or next(l for l in LANGS if l!=source)
    if source==target and request.args.get('lang'):target=next(l for l in LANGS if l!=source)
    if source not in LANGS or target not in LANGS or source==target: abort(400)
    with connect() as db, db.cursor() as c:
        c.execute('''SELECT a.*, (SELECT COUNT(*) FROM passage p WHERE p.lang=a.lang AND p.page_id=a.page_id AND p.model=%s) AS passages
          FROM article a WHERE wikidata_id=%s''',(MODEL,topic))
        articles={a['lang']:a for a in c.fetchall()}
        if not articles: abort(404)
        rows=compare(c,topic,source,target) if source in articles and target in articles else []
    title=articles.get('en',next(iter(articles.values())))['title']
    from mock_review import mock_review, CATEGORIES
    from pipeline import latest, review_candidates
    demo=request.args.get('demo')=='1';run,findings=latest(topic)
    if demo: findings,review_counts=review_candidates(mock_review(topic,articles))
    else: review_counts=run['review_counts'] if run else {'equivalent':0,'uncertain':0,'actionable':0,'exact_duplicates':0}
    from review_view import select_languages,section_groups
    try: selected_languages=select_languages(request.args.getlist('languages') or (session.get('showcase_languages',['en','fi','sv']) if topic=='Q2606233' and not demo else []),articles,source,target)
    except ValueError as error:
        if not request.args.getlist('languages') and len(articles)<2:selected_languages=list(articles)
        else: abort(400,description=str(error))
    current_lang=source if source in articles else next(iter(articles))
    findings=[dict(f,evidence=sorted(f['evidence'],key=lambda e:e['lang']!=current_lang)) for f in findings]
    findings,sections=section_groups(findings,selected_languages)
    review_counts=dict(review_counts,actionable=sum(f['category']!='uncertain' for f in findings),uncertain=sum(f['category']=='uncertain' for f in findings))
    session.setdefault('review_token',secrets.token_hex(24))
    return dict(historical=False,topic=topic,title=title,articles=articles,source=source,target=target,rows=rows,langs=LANGS,
        findings=findings,categories=CATEGORIES,review_counts=review_counts,selected_languages=selected_languages,
        review_sections=sections,current_lang=current_lang,demo=demo,run=run,review_token=session['review_token'])

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key=secrets.token_hex(32)

@app.before_request
def browser_review_token():
    session.setdefault('review_token',secrets.token_hex(24))

@app.errorhandler(pymysql.MySQLError)
def database_error(error):
    app.logger.error('Database unavailable: %s',error)
    return render_template('error.html'),503

@app.get('/')
def home():
    return redirect('/explore')

@app.get('/articles')
def index():
    q=request.args.get('q','').strip()[:150]
    with connect() as db, db.cursor() as c:
        c.execute('''SELECT a.wikidata_id, COALESCE(MAX(CASE WHEN a.lang='en' THEN a.title END),MAX(a.title)) AS title,
          GROUP_CONCAT(DISTINCT a.lang ORDER BY a.lang) AS languages,
          COUNT(DISTINCT p.lang) AS prepared
          FROM article a LEFT JOIN passage p ON p.lang=a.lang AND p.page_id=a.page_id AND p.model=%s
          WHERE a.wikidata_id IS NOT NULL AND (%s='' OR a.wikidata_id IN
          (SELECT wikidata_id FROM article WHERE title LIKE %s))
          GROUP BY a.wikidata_id ORDER BY prepared DESC, title LIMIT 40''',(MODEL,q,'%'+q+'%'))
        topics=c.fetchall()
        c.execute('SELECT COUNT(*) AS n FROM article')
        count=c.fetchone()['n']
    return render_template('index.html',topics=topics,q=q,count=count)

@app.get('/wiki/<topic>')
def article_page(topic):
    from article_render import render_article
    from flags_routes import fixture_context
    fixture=fixture_context(topic)
    if fixture is None and not re.fullmatch(r'Q\d+',topic): abort(404)
    lang=request.args.get('lang')
    if lang is not None and lang not in LANGS: abort(400)
    if fixture is not None:
        articles={code:dict(value,page_id=0,rev_id=0,date_modified='offline fixture',url='')
                  for code,value in fixture['articles'].items()}
    else:
        with connect() as db, db.cursor() as c:
            c.execute('SELECT * FROM article WHERE wikidata_id=%s',(topic,))
            articles={a['lang']:a for a in c.fetchall()}
    if not articles: abort(404)
    if lang and lang not in articles: abort(404,description='This language is absent from the local snapshot.')
    lang=lang or next(l for l in ('en','fi','sv') if l in articles)
    article=articles[lang]
    body,contents=render_article(article['text'],lang,article['title'])
    target=next(l for l in ('fi','en','sv') if l!=lang)
    if fixture is not None:
        article_run,article_findings,watch_notices=None,[],[]
    else:
        from pipeline import latest
        article_run,article_findings=latest(topic)
        from watchlist import overview
        watch_notices,_=overview(topic)
    if topic=='Q2606233':
        from review_view import section_groups
        article_findings,_=section_groups(article_findings,session.get('showcase_languages',['en','fi','sv']))
    return render_template('article.html',topic=topic,article=article,articles=articles,
        lang=lang,target=target,body=body,article_contents=contents,
        article_run=article_run,article_findings=[f for f in article_findings if f['category']!='same'],
        watch_pending=sum(n['status'] in ('pending','needs_update') and n['data'].get('revision_kind')!='sandbox' for n in watch_notices))

@app.get('/langcompare/<topic>')
@app.get('/topic/<topic>')
def topic_page(topic):
    if not re.fullmatch(r'Q\d+',topic): abort(404)
    if any(key in request.args for key in ('run','group','stamp','occurrence')):
        from skyline import tracker_context
        args=request.args.copy();args['topic']=topic
        try:return render_template('topic.html',**tracker_context(topic,args))
        except ValueError as error:return render_template('historical_unavailable.html',topic=topic,message=str(error)),400
        except LookupError as error:return render_template('historical_unavailable.html',topic=topic,message=str(error)),404
    return render_template('topic.html',**comparison_context(topic))

@app.post('/reviews/<topic>')
def start_review(topic):
    if not re.fullmatch(r'Q\d+',topic): abort(404)
    if not secrets.compare_digest(request.form.get('token',''),session.get('review_token','invalid')): abort(403)
    if request.headers.get('Sec-Fetch-Site')=='cross-site': abort(403)
    from pipeline import enqueue
    try: enqueue(topic)
    except ValueError as e: abort(400,description=str(e))
    if topic=='Q2606233':
        from showcase_routes import start_analysis
        start_analysis()
    return redirect('/langcompare/'+topic,code=303)

@app.get('/reviews/<topic>/status')
def review_status(topic):
    if not re.fullmatch(r'Q\d+',topic): abort(404)
    from pipeline import latest
    run,findings=latest(topic)
    return jsonify(run={k:run[k] for k in ('id','status','progress','total','error')} if run else None,findings=len(findings))

@app.get('/reviews')
def review_dashboard():
    from pipeline import VERSION
    with connect() as db,db.cursor() as c:
        c.execute('''SELECT r.topic,r.status,r.progress,r.total,r.error,r.updated,
          COALESCE(MAX(CASE WHEN a.lang='en' THEN a.title END),MAX(a.title)) AS title
          FROM review_run r JOIN article a ON a.wikidata_id=r.topic
          WHERE r.version=%s GROUP BY r.id ORDER BY r.created''',(VERSION,)); runs=c.fetchall()
        c.execute('''SELECT COUNT(*) AS requests,COALESCE(SUM(cost),0) AS cost,
          COALESCE(SUM(CASE WHEN status<>'done' THEN reserved ELSE 0 END),0) AS reserved,
          COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens
          FROM api_call'''); usage=c.fetchone()
        c.execute('SELECT report FROM review_evaluation WHERE id=1'); evaluation=c.fetchone()
    return render_template('dashboard.html',runs=runs,usage=usage,evaluation=json.loads(evaluation['report']) if evaluation else None)

@app.post('/topic/<topic>/verify')
def verify(topic):
    if not re.fullmatch(r'Q\d+',topic): abort(404)
    with connect() as db, db.cursor() as c:
        c.execute('SELECT 1 FROM article WHERE wikidata_id=%s LIMIT 1',(topic,))
        if not c.fetchone(): abort(404)
        c.execute('SELECT result FROM verification WHERE wikidata_id=%s AND checked_at > UTC_TIMESTAMP() - INTERVAL 1 DAY',(topic,))
        cached=c.fetchone()
        if cached: return jsonify(json.loads(cached['result']))
        try:
            r=requests.get('https://www.wikidata.org/w/api.php',params={
                'action':'wbgetentities','ids':topic,'props':'sitelinks/urls','format':'json'},
                headers={'User-Agent':'WikipediaLanguageGapExplorer/0.1 (local editor research prototype)'},timeout=(5,15))
            r.raise_for_status()
            links=r.json()['entities'][topic]['sitelinks']
            result={'checked_at':datetime.now(timezone.utc).isoformat(), 'languages':{
                lang: {'status':'Live page exists' if lang+'wiki' in links else 'No current language link found',
                       'url':links.get(lang+'wiki',{}).get('url')} for lang in LANGS}}
        except (requests.RequestException,KeyError,ValueError):
            return jsonify(error='Live verification is unavailable. Language availability is unknown; try again later.'),502
        c.execute('REPLACE INTO verification(wikidata_id,checked_at,result) VALUES (%s,UTC_TIMESTAMP(),%s)',(topic,json.dumps(result)))
    return jsonify(result)

def update_issue_count(rows,lang):
    from update_issues import issue_items
    from showcase_history import edition_reviews
    try:reviews=edition_reviews(lang)
    except pymysql.MySQLError:return 0
    return sum(reviews.get(i['id'],{}).get('action','pending') in ('pending','needs_update') for i in issue_items(rows,lang))

@app.context_processor
def showcase_context():
    from urllib.parse import urlencode
    chosen=request.args.getlist('languages')
    if 2<=len(set(chosen))<=3 and all(l in LANGS for l in chosen):session['showcase_languages']=list(dict.fromkeys(chosen))
    chosen=session.get('showcase_languages',['en','fi','sv'])
    current_lang=request.args.get('lang') or (request.args.get('source') if request.endpoint=='topic_page' else None) or session.get('showcase_article_language','en')
    if current_lang not in LANGS:current_lang='en'
    session['showcase_article_language']=current_lang
    query='lang='+current_lang+'&'+urlencode([('languages',l) for l in chosen])
    topic=(request.view_args or {}).get('topic')
    if topic=='Q134949':
        timeline_lang=request.args.get('lang',current_lang)
        if timeline_lang not in ('en','fi','sv','ru'):timeline_lang='en'
        return dict(showcase=True,showcase_languages=chosen,
            showcase_article_url='/wiki/Q134949?'+query,
            showcase_compare_url='/langcompare/Q134949?'+query,
            showcase_updates_url='/watchlist?topic=Q134949',
            showcase_timeline_url='/wiki/Q134949/timeline?lang='+timeline_lang,
            historical_pending=0,history_range='')
    if topic!='Q2606233':return {}
    from showcase_history import events
    try:rows,status=events()
    except pymysql.MySQLError:rows,status=[],None
    return dict(showcase=True,showcase_languages=chosen,showcase_article_url='/wiki/Q2606233?'+query,
        showcase_compare_url='/langcompare/Q2606233?'+query,showcase_updates_url='/wiki/Q2606233/updates?'+query,
        historical_pending=update_issue_count(rows,current_lang),
        history_range=(min(r['stamp'] for r in rows)+' - '+max(r['stamp'] for r in rows)) if rows else '')

if _MYSQL_AVAILABLE:
    from showcase_routes import bp as showcase_blueprint
    app.register_blueprint(showcase_blueprint)
    from watch_routes import bp as watch_blueprint
    app.register_blueprint(watch_blueprint)
    from timeline_routes import bp as timeline_blueprint
    app.register_blueprint(timeline_blueprint)
    from discrepancy_explorer import bp as discrepancy_explorer_blueprint
    app.register_blueprint(discrepancy_explorer_blueprint)
from flags_routes import bp as flags_blueprint
app.register_blueprint(flags_blueprint)

if __name__=='__main__':
    from pipeline import init
    init()
    from watchlist import init as init_watch
    from local_translation import init as init_translation
    init_watch();init_translation()
    from showcase_history import init as init_history
    init_history()
    from semantic_timeline import init as init_timeline
    init_timeline()
    app.run(host='127.0.0.1',port=8010,debug=False)

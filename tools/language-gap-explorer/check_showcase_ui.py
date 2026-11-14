"""Offline render QA using actual snapshot text and cached historical revisions.
Does not establish database/worker integration; run full integration after Docker recovery.
"""
import json,re
from pathlib import Path
from unittest.mock import patch
import pyarrow.parquet as pq
from playwright.sync_api import sync_playwright
from flask import render_template
from app import app
from article_render import render_article
from showcase_history import TOPIC,api,revision,changes
from watchlist import diff_html
from core import ROOT
articles={}
for lang in ('en','fi','sv'):
 a=pq.read_table(ROOT/'data'/('articles-'+lang+'.parquet'),filters=[('wikidata_id','=',TOPIC)]).to_pylist()[0];a['passages']=0;articles[lang]=a
article=articles['en'];vv=api('en',dict(action='query',prop='revisions',pageids=article['page_id'],rvstartid=article['rev_id'],rvlimit=20,rvprop='ids|timestamp|comment'))['query']['pages'][0]['revisions']
event=None
for v in vv:
 before=revision('en',v['parentid']);after=revision('en',v['revid']);diffs=changes(before,after)
 if diffs:
  event=dict(id='offline-render',lang='en',before_rev=v['parentid'],after_rev=v['revid'],stamp=v['timestamp'],summary=v.get('comment',''),kind='prose',status='pending',note=None,check=None,data={'changes':[dict(d,counterparts=[]) for d in diffs]});break
assert event,'No cached prose edit available for visual verification'
body,contents=render_article(article['text'],'en',article['title'])
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge',headless=True);page=b.new_page()
 for path,template,context in [('/wiki/'+TOPIC,'article.html',dict(article=article,articles=articles,lang='en',target='fi',body=body,article_contents=contents,article_run=None,article_findings=[],watch_pending=0)),('/wiki/'+TOPIC+'/updates','updates.html',dict(title='Tornedalians',issues=[],counts={'open':0,'closed':0},target='en',kind='all',order='newest',issue_total=0,history_status={'message':'Offline render QA with a real cached edit; database integration pending.'},history_total=1,prose_total=1,mode='pending',page=1,has_next=False,diff_html=diff_html)),('/langcompare/'+TOPIC,'topic.html',dict(title='Tornedalians',articles=articles,source='en',target='sv',rows=[],langs=('en','fi','sv'),findings=[],categories={},review_counts={'equivalent':0},selected_languages=['en','fi','sv'],review_sections=[],demo=False,run=None,review_token='preview'))]:
  with app.test_request_context(path),patch('showcase_history.events',return_value=([event],None)),patch('showcase_history.edition_reviews',return_value={}):
   html=render_template(template,topic=TOPIC,**context)
  # Inline committed CSS; this isolated render does not issue network/paid calls.
  html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
  html=html.replace('<link rel="stylesheet" href="/static/style.css">','<style>'+ (ROOT/'static/style.css').read_text(encoding='utf-8')+'</style>')
  for width,height,label in ((1440,1000,'desktop'),(390,844,'mobile')):
   page.set_viewport_size({'width':width,'height':height});page.set_content(html)
   assert page.locator('.showcase-tabs a:visible').count()==3
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   filename=template.replace('.html','')
   page.screenshot(path=str(ROOT/'screenshots'/f'showcase-{filename}-{label}.png'))
 b.close()
print('Offline render checks passed: real article, cached historical edit, comparison empty state; desktop/mobile. Database integration not tested.')

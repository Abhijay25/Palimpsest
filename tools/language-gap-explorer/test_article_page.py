import os
import unittest
from unittest.mock import patch
class ArticlePageTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'LANGGAP_FIXTURES':'1'},clear=False);self.env.start()
        from app import app
        self.client=app.test_client()
    def tearDown(self): self.env.stop()
    def test_fixture_flags_page_has_accessible_tabs_and_cached_audit(self):
        with patch('flags_routes.requests.post',side_effect=AssertionError('GET must not scan')): response=self.client.get('/article/Q-demo?tab=flags')
        page=response.get_data(as_text=True);self.assertEqual(response.status_code,200);self.assertIn('aria-label="Article views"',page);self.assertIn('aria-current="page"',page);self.assertIn('Scan 3 revisions',page);self.assertIn('flags-workspace',page);self.assertIn('Prior revision',page);self.assertIn('Selected revision',page);self.assertIn('mw-diff-inline',page);self.assertIn('aria-label="NeoWiki audit summary"',page);self.assertNotIn('Palimpsest audit summary',page)
    def test_fixture_language_page_and_revision_api_are_database_free(self):
        response=self.client.get('/article/Q-demo?tab=language');self.assertEqual(response.status_code,200);self.assertIn('Synthetic offline fixture',response.get_data(as_text=True));payload=self.client.get('/api/flags/revisions?topic=Q-demo&lang=en').get_json();self.assertEqual([row['revision'] for row in payload['revisions']],[102,103,101])
    def test_fixture_wiki_page_links_to_language_and_flags_tabs(self):
        response=self.client.get('/wiki/Q-demo?lang=en')
        page=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('aria-label="Article views"',page)
        self.assertIn('/article/Q-demo/issues?lang=en&amp;tab=issues',page)
        self.assertNotIn('id="flags-tab"',page)
    def test_default_article_view_does_not_fetch_history_or_scan(self):
        with patch('flags_routes.fetch_history',side_effect=AssertionError('Reader must not fetch history')), patch('flags_routes.requests.post',side_effect=AssertionError('GET must not scan')):
            response=self.client.get('/article/Q-demo?lang=en')
        page=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('class="wiki-article"',page)
        self.assertIn('Issues',page)
        self.assertNotIn('Read this edition in the',page)

    def test_reader_labels_a_different_selected_detector_revision(self):
        response=self.client.get('/article/Q-demo?lang=en&tab=article&revision=103')
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertIn('Flags tab has revision 103 selected',page)
        self.assertIn('oldid=103',page)

    def test_tab_links_preserve_exact_historical_context(self):
        from html import unescape
        from urllib.parse import urlsplit,parse_qs
        import re
        query='run='+'a'*64+'&group='+'b'*64+'&stamp=2025-01-01T00:00:00Z&occurrence='+'c'*64+'&languages=en&languages=sv&revision=102&lang=en&tab=flags&scan=1'
        with patch('flags_routes.requests.post',side_effect=AssertionError('GET must not scan')):
            response=self.client.get('/article/Q-demo?'+query)
        page=response.get_data(as_text=True)
        links=re.findall(r'id="(?:article|issues)-tab"[^>]*href="([^"]+)"',page)
        self.assertEqual(len(links),2)
        for link in links:
            args=parse_qs(urlsplit(unescape(link)).query)
            self.assertEqual(args['occurrence'],['c'*64])
            self.assertEqual(args['languages'],['en','sv'])
            self.assertEqual(args['revision'],['102'])
            self.assertEqual(args['run'],['a'*64])
            self.assertEqual(len(args['tab']),1)
            self.assertNotIn('scan',args)

    def test_real_flags_context_does_not_render_missing_comparison_data(self):
        context=dict(topic='Q123',title='Real article',current_lang='en',articles={'en':dict(title='Real article')},standalone=True,block_revisions=[])
        with patch('flags_routes.tracker_or_fixture',return_value=context), patch('flags_routes.fixture_enabled',return_value=False):
            response=self.client.get('/article/Q123?tab=flags&tools=1')
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertIn('History unavailable',page)
        self.assertNotIn('id="language-panel"',page)

    def test_historical_article_never_substitutes_snapshot(self):
        context=dict(topic='Q123',title='Historic article',historical=True,current_lang='en',historical_date='1 Jan 2025',historical_back='/explore',historical_evidence=[dict(lang='en',title='Historic article',rev_id=42,stamp='2025-01-01',quote='Exact archived wording.',url='https://en.wikipedia.org/w/index.php?oldid=42')])
        with patch('flags_routes.tracker_or_fixture',return_value=context), patch('app.connect',side_effect=AssertionError('Must not read a snapshot')):
            response=self.client.get('/article/Q123?tab=article&run='+'a'*64)
        page=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('Exact archived wording.',page)
        self.assertIn('oldid=42',page)
        self.assertIn('current snapshot has not been substituted',page)

    def test_fixture_page_consistency_proxy_returns_two_flags_without_detector(self):
        with patch('flags_routes.requests.post',side_effect=AssertionError('fixture page check must stay offline')):
            response=self.client.post('/api/flags/page',json={'topic':'Q-demo','lang':'en','revision':102,'scan':True})
        payload=response.get_json()
        self.assertEqual(response.status_code,200)
        self.assertEqual(payload['status'],'ok')
        self.assertEqual(len(payload['flags']),2)
        self.assertIn('Volunteers recorded arrivals.',payload['page_html'])
if __name__=='__main__': unittest.main()

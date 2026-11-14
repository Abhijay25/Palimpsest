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
        with patch('flags_routes.requests.post',side_effect=AssertionError('GET must not scan')): response=self.client.get('/article/Q-demo?tab=flags&lang=en&run=demo&group=one')
        page=response.get_data(as_text=True);self.assertEqual(response.status_code,200);self.assertIn('role="tablist"',page);self.assertIn('aria-current="page"',page);self.assertIn('Re-check',page);self.assertIn('/article/Q-demo?lang=en&amp;run=demo&amp;group=one&amp;tab=language',page);self.assertIn('/article/Q-demo?lang=en&amp;run=demo&amp;group=one&amp;tab=flags',page);self.assertIn('flags-workspace',page);self.assertIn('Prior revision',page);self.assertIn('Selected revision',page);self.assertIn('mw-diff-inline',page);self.assertIn('Palimpsest audit summary',page)
    def test_fixture_language_page_and_revision_api_are_database_free(self):
        response=self.client.get('/article/Q-demo?tab=language');self.assertEqual(response.status_code,200);self.assertIn('Synthetic offline fixture',response.get_data(as_text=True));payload=self.client.get('/api/flags/revisions?topic=Q-demo&lang=en').get_json();self.assertEqual([row['revision'] for row in payload['revisions']],[102,103,101])
    def test_fixture_wiki_page_links_to_language_and_flags_tabs(self):
        response=self.client.get('/wiki/Q-demo?lang=en')
        page=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('role="tablist"',page)
        self.assertIn('/article/Q-demo?lang=en&amp;tab=language',page)
        self.assertIn('/article/Q-demo?lang=en&amp;tab=flags',page)
    def test_fixture_page_consistency_proxy_returns_two_flags_without_detector(self):
        with patch('flags_routes.requests.post',side_effect=AssertionError('fixture page check must stay offline')):
            response=self.client.post('/api/flags/page',json={'topic':'Q-demo','lang':'en','revision':102,'scan':True})
        payload=response.get_json()
        self.assertEqual(response.status_code,200)
        self.assertEqual(payload['status'],'ok')
        self.assertEqual(len(payload['flags']),2)
        self.assertIn('Volunteers recorded arrivals.',payload['page_html'])
if __name__=='__main__': unittest.main()

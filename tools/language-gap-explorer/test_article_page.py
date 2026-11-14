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
        page=response.get_data(as_text=True);self.assertEqual(response.status_code,200);self.assertIn('role="tablist"',page);self.assertIn('aria-current="page"',page);self.assertIn('Scan 3 revisions',page);self.assertIn('flags-workspace',page);self.assertIn('Prior revision',page);self.assertIn('Selected revision',page);self.assertIn('mw-diff-inline',page);self.assertIn('Palimpsest audit summary',page)
    def test_fixture_language_page_and_revision_api_are_database_free(self):
        response=self.client.get('/article/Q-demo?tab=language');self.assertEqual(response.status_code,200);self.assertIn('Synthetic offline fixture',response.get_data(as_text=True));payload=self.client.get('/api/flags/revisions?topic=Q-demo&lang=en').get_json();self.assertEqual([row['revision'] for row in payload['revisions']],[102,103,101])
if __name__=='__main__': unittest.main()

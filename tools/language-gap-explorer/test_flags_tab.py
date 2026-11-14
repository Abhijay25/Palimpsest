import os
import tempfile
import unittest
from unittest.mock import patch
from flags_tab import RevisionRef, audit_payload, block_revisions, rank_revisions

class FlagsTabTests(unittest.TestCase):
    def test_block_revisions_scopes_to_current_edition_and_deduplicates(self):
        context={'current_lang':'fi','title':'Example','historical_occurrences':[{'evidence':[{'lang':'en','revision':4},{'lang':'fi','revision':8,'stamp':'2025-01-01'},{'lang':'fi','revision':8}]}]}
        self.assertEqual(block_revisions(context),[RevisionRef('fi',8,'Example','2025-01-01','',None)])
    def test_rank_prefers_admin_then_counts_and_is_stable(self):
        rows=[{'revision':1,'flags':[{'tier':'review'}]},{'revision':2,'flags':[{'tier':'admin'}]},{'revision':3,'flags':[{'tier':'admin'},{'tier':'review'}]},{'revision':4,'flags':[]}]
        self.assertEqual([r['revision'] for r in rank_revisions(rows)],[3,2,1,4])
    def test_payload_matches_audit_diff_contract(self):
        ref=RevisionRef('en',12,'Example',parent_id=11,url='https://example.test/rev');body=audit_payload(ref,'old','new')
        self.assertEqual(set(body),{'lang_code','page_title','old_revision_id','new_revision_id','editor_username','old_text','new_text','old_wikitext','new_wikitext','ref_urls'});self.assertEqual(body['old_revision_id'],11)
    def test_diff_is_a_side_by_side_word_diff_with_anchor_cells(self):
        from flags_routes import diff_html
        rendered=diff_html('The harbor used blue lamps in winter.','The harbor used blue lamps in winter. Volunteers recorded arrivals.')
        self.assertIn('Prior revision',rendered);self.assertIn('Selected revision',rendered);self.assertIn('data-diff-side="old"',rendered);self.assertIn('data-diff-side="new"',rendered);self.assertIn('<ins class="diffchange"> Volunteers recorded arrivals.</ins>',rendered)
    def test_proxy_stores_detector_response(self):
        from flags_routes import response_payload
        ref=RevisionRef('en',22,'Example',parent_id=21)
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'flags':[{'id':'one','tier':'review'}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False), patch('flags_routes.fetch_revision',side_effect=[{'parent_id':21,'title':'Example','wikitext':'new'}, {'wikitext':'old'}]), patch('flags_routes.requests.post',return_value=Response()) as post:
            first=response_payload(ref,{},True);second=response_payload(ref,{},False)
        self.assertEqual(first['status'],'ok');self.assertEqual(second['status'],'ok');post.assert_called_once();self.assertIn('mw-diff-inline-added',first['diff_html'])
if __name__=='__main__': unittest.main()

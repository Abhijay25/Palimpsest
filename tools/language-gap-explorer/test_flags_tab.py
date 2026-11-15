import os
import json
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
        self.assertIn('Prior revision',rendered);self.assertIn('Selected revision',rendered);self.assertIn('Line 1:',rendered);self.assertIn('data-diff-side="old"',rendered);self.assertIn('data-diff-side="new"',rendered);self.assertIn('<ins class="diffchange"> Volunteers recorded arrivals.</ins>',rendered)
    def test_diff_collapses_unchanged_lines_between_two_line_context_hunks(self):
        from flags_routes import diff_html
        old='\n'.join('Line '+str(index) for index in range(1,21))
        rendered=diff_html(old,old.replace('Line 4','Changed 4').replace('Line 17','Changed 17'))
        self.assertIn('unchanged lines collapsed',rendered);self.assertIn('Line 2:',rendered);self.assertIn('Line 15:',rendered);self.assertNotIn('Line 10</td>',rendered)
    def test_proxy_stores_detector_response(self):
        from flags_routes import response_payload
        ref=RevisionRef('en',22,'Example',parent_id=21)
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'flags':[{'id':'one','tier':'review'}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False), patch('flags_routes.fetch_revision',side_effect=[{'parent_id':21,'title':'Example','wikitext':'new'}, {'wikitext':'old'}]), patch('flags_routes.requests.post',return_value=Response()) as post:
            first=response_payload(ref,{},True);second=response_payload(ref,{},False)
        self.assertEqual(first['status'],'ok');self.assertEqual(second['status'],'ok');self.assertTrue(second['stored']);self.assertIn('stored_at',second);self.assertNotIn('page_created',first);self.assertNotIn('truncated',first);post.assert_called_once();self.assertEqual(post.call_args.kwargs['json']['old_wikitext'],'old');self.assertEqual(post.call_args.kwargs['json']['new_wikitext'],'new');self.assertIn('mw-diff-inline-added',first['diff_html'])
    def test_page_creation_audits_empty_old_text_and_bounds_first_version(self):
        from flags_routes import PAGE_CREATION_TEXT_LIMIT,response_payload
        ref=RevisionRef('en',22,'Example',parent_id=0);new='a'*PAGE_CREATION_TEXT_LIMIT+'after limit'
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'flags':[]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False), patch('flags_routes.fetch_revision',return_value={'parent_id':0,'title':'Example','wikitext':new}) as fetch, patch('flags_routes.requests.post',return_value=Response()) as post:
            result=response_payload(ref,{},True)
            cached=json.loads(open(os.path.join(directory,'audits','en-22.json'),encoding='utf-8').read())
        self.assertEqual(result['status'],'ok');self.assertTrue(result['page_created']);self.assertTrue(result['truncated']);fetch.assert_called_once();self.assertEqual(post.call_args.kwargs['json']['old_wikitext'],'');self.assertEqual(post.call_args.kwargs['json']['new_wikitext'],'a'*PAGE_CREATION_TEXT_LIMIT);self.assertNotIn('after limit',result['diff_html']);self.assertTrue(cached['page_created'])
    def test_hidden_or_deleted_parent_is_unavailable(self):
        from flags_routes import response_payload
        ref=RevisionRef('en',22,'Example',parent_id=21)
        for parent in (RuntimeError('revision content missing'),{'texthidden':''},{'missing':''}):
            with self.subTest(parent=parent), patch('flags_routes.fetch_revision',side_effect=[{'parent_id':21,'title':'Example','wikitext':'new'},parent]), patch('flags_routes.requests.post') as post:
                result=response_payload(ref,{},True)
            self.assertEqual(result,{'status':'unavailable','flags':[],'error':'The previous revision is hidden or deleted, so this edit cannot be compared.'});post.assert_not_called()
    def test_fresh_audit_bypasses_cache_and_forwards_detector_header(self):
        from flags_routes import response_payload
        ref=RevisionRef('en',22,'Example',parent_id=21)
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'flags':[]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False), patch('flags_routes.fetch_revision',side_effect=[{'parent_id':21,'title':'Example','wikitext':'new'}, {'wikitext':'old'}]), patch('flags_routes.requests.post',return_value=Response()) as post:
            response_payload(ref,{},True,True)
        self.assertEqual(post.call_args.kwargs['headers'],{'X-Palimpsest-Fresh':'1'})
    def test_fresh_audit_is_enabled_only_by_the_page_query_parameter(self):
        from app import app
        with patch.dict(os.environ,{'LANGGAP_FIXTURES':'1'},clear=False), patch('flags_routes.response_payload',return_value={'status':'ok','flags':[]}) as response:
            with app.test_client() as client:
                client.post('/api/flags/audit',json={'topic':'Q-demo','lang':'en','revision':101,'scan':True,'fresh':True})
                self.assertFalse(response.call_args.args[3])
                client.post('/api/flags/audit?fresh=1',json={'topic':'Q-demo','lang':'en','revision':101,'scan':True})
        self.assertTrue(response.call_args.args[3])
    def test_history_cache_has_ten_minute_ttl_and_live_history_has_required_fields(self):
        from revision_text import HISTORY_TTL_SECONDS,cached_history,fetch_history,history_cache_path
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*_args): return False
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False):
            path=history_cache_path('en',7);path.parent.mkdir(parents=True);path.write_text(json.dumps({'cached_at':100,'revisions':[{'revision':1}]}),encoding='utf-8')
            self.assertIsNotNone(cached_history('en',7,100+HISTORY_TTL_SECONDS))
            self.assertIsNone(cached_history('en',7,101+HISTORY_TTL_SECONDS))
            reply=Reply();reply.read=lambda *_args: b'{"query":{"pages":{"7":{"title":"Example","revisions":[{"revid":9,"parentid":8,"timestamp":"2025-01-01T00:00:00Z","user":"Editor","comment":"note","size":42}]}}}}'
            with patch('revision_text.urlopen',return_value=reply) as open_url:
                rows=fetch_history('en',7,9,'Example')
        self.assertEqual(rows[0]['user'],'Editor');self.assertEqual(rows[0]['comment'],'note')
        self.assertIn('rvprop=ids%7Ctimestamp%7Cuser%7Ccomment%7Csize',open_url.call_args.args[0].full_url)
    def test_page_proxy_contract_and_fresh_header(self):
        from flags_routes import page_response_payload
        ref=RevisionRef('en',22,'Example')
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'status':'ok','flags':[{'kind':'OUT_OF_SYNC','evidence':[{'source':'page','quote':'Other sentence','section':'Lead'}]}]}
        context={'articles':{'en':{'text':'Current sentence.'}}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory},clear=False), patch('flags_routes.fetch_revision',return_value={'wikitext':'Current sentence.'}), patch('flags_routes.requests.post',return_value=Response()) as post:
            result=page_response_payload(ref,context,True,True)
        self.assertEqual(result['status'],'ok');self.assertIn('Current sentence.',result['page_html'])
        self.assertEqual(post.call_args.args[0].rsplit('/',1)[-1],'audit-page')
        self.assertEqual(post.call_args.kwargs['json'],{'lang_code':'en','page_title':'Example','revision_id':22,'wikitext':'Current sentence.'})
        self.assertEqual(post.call_args.kwargs['headers'],{'X-Palimpsest-Fresh':'1'})
if __name__=='__main__': unittest.main()

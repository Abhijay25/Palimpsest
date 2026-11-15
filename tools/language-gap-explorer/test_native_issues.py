import hashlib
import hmac
import json
import unittest
from unittest.mock import patch,MagicMock
from native_issues import Arguments,authenticated,dispatch,detector_catalog,native_url


class NativeIssuesTests(unittest.TestCase):
    def test_signature_binds_body_and_expires(self):
        secret='x'*48;body=b'{"op":"list"}';stamp='1000'
        signature=hmac.new(secret.encode(),stamp.encode()+b'\n'+body,hashlib.sha256).hexdigest()
        self.assertTrue(authenticated(body,stamp,signature,secret,current=1001))
        self.assertFalse(authenticated(b'{"op":"scan"}',stamp,signature,secret,current=1001))
        self.assertFalse(authenticated(body,stamp,signature,secret,current=1061))
        self.assertFalse(authenticated(body,'bad',signature,secret,current=1001))
        self.assertFalse(authenticated(body,stamp,signature,'short',current=1001))

    def test_native_list_cannot_use_preview_review_identity_or_start_inference(self):
        payload=dict(title='Winter War',edition='en',wiki='mw_native_en',source_page_id=12,query={'scan':'1','languages':['fi','sv']})
        with patch('native_issues.article_topic',return_value='Q1'),patch('issues.list_issues',return_value={'issues':[]}) as read,patch('flags_routes.response_payload',side_effect=AssertionError('No inference')):
            self.assertEqual(dispatch(payload)['topic'],'Q1')
            self.assertEqual(read.call_args.kwargs,dict(review_scope='mw_native_en'))
            self.assertEqual(read.call_args.args[1].getlist('languages'),['fi','sv'])
            with self.assertRaises(ValueError):dispatch(dict(payload,wiki=''))

    def test_exact_detail_rejects_mismatched_editions_kind_and_run(self):
        payload=dict(op='detail',title='Winter War',edition='fi',wiki='wiki_fi',query={'issue':'i','observation':'o','occurrence':'exact','kind':'coverage'})
        row=dict(mode='language',kind='framing',languages=['fi','sv'],context={'run':'original'})
        with patch('native_issues.article_topic',return_value='Q1'),patch('issues.get_observation',return_value=row):
            with self.assertRaises(LookupError):dispatch(payload)
            payload['query']={'issue':'i','languages':['en','fi']}
            with self.assertRaises(LookupError):dispatch(payload)
            payload['query']={'issue':'i','run':'other'}
            with self.assertRaises(LookupError):dispatch(payload)

    def test_scan_rejects_source_local_hash_mismatch_before_detector(self):
        payload=dict(op='scan',title='Winter War',edition='en',wiki='wiki_en',source=dict(revision_id=123,lang='en',title='Winter War',sha256='0'*64))
        with patch('native_issues.article_topic',return_value='Q1'),patch('native_issues.archived_scan',return_value=None),patch('revision_text.cached_revision',return_value=None),patch('flags_routes.cached_audit',return_value=None),patch('flags_routes.pending_result',return_value=None),patch('revision_text.fetch_revision',return_value={'wikitext':'Actual source'}),patch('flags_routes.response_payload') as scan:
            with self.assertRaises(LookupError):dispatch(payload)
            scan.assert_not_called()

    def test_cached_source_absence_does_not_fetch(self):
        payload=dict(op='cached',title='Winter War',edition='en',wiki='wiki_en',source=dict(revision_id=123,lang='en',title='Winter War',sha256='0'*64))
        with patch('native_issues.article_topic',return_value='Q1'),patch('native_issues.archived_scan',return_value=None),patch('revision_text.cached_revision',return_value=None),patch('flags_routes.cached_audit',return_value=None),patch('revision_text.fetch_revision') as fetch:
            with self.assertRaises(LookupError):dispatch(payload)
            fetch.assert_not_called()

    def test_preserved_audit_reads_without_separate_source_download(self):
        text='Preserved exact source';payload=dict(op='cached',title='Winter War',edition='en',wiki='wiki_en',source=dict(revision_id=123,lang='en',title='Winter War',sha256=hashlib.sha256(text.encode()).hexdigest()))
        with patch('native_issues.article_topic',return_value='Q1'),patch('native_issues.archived_scan',return_value=None),patch('revision_text.cached_revision',return_value=None),patch('flags_routes.cached_audit',return_value=dict(new_wikitext=text)),patch('revision_text.fetch_revision') as fetch,patch('flags_routes.response_payload',return_value=dict(status='ok',flags=[])) as read:
            self.assertEqual(dispatch(payload)['status'],'ok')
            self.assertFalse(read.call_args.args[2]);fetch.assert_not_called()

    def test_detector_catalog_keeps_identity_time_empty_failure_and_partial(self):
        cursor=MagicMock();cursor.__enter__.return_value=cursor
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value=cursor
        found=[dict(id='one',title='Same title',observation='o1',kind='FACT',stamp='2020-01-01',languages='en',assessment_id='a',assessed_at='2026-01-01',mode='revision'),
            dict(id='two',title='Same title',observation='o2',kind='FRAMING',stamp='2020-02-01',languages='fi',assessment_id='b',assessed_at='2026-02-01',mode='page')]
        scope=dict(lang='en',revision=22,mode='revision')
        coverage=[dict(scope=json.dumps(scope),state='failed',assessed_at='2026-03-01',note='failure')]
        assessment=dict(id='empty',mode='revision',assessed_at='2026-01-01',payload=json.dumps(dict(ref=dict(lang='en',revision_id=22,timestamp='2020-01-01'),result={'flags':[]})))
        partial=dict(id='partial',mode='page',assessed_at='2026-02-01',payload=json.dumps(dict(ref=dict(lang='fi',revision_id=23,timestamp='2020-02-01'),result={'flags':[],'partial':True})))
        cursor.fetchall.side_effect=[found,coverage,[assessment,partial]]
        with patch('native_issues.connect',return_value=db):result=detector_catalog('Q1',['en','fi'])
        self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['time_axis'],'source_edit')
        self.assertEqual(result['rows'][0]['cells'][0]['stamp'],'2020-01-01')
        self.assertEqual(result['rows'][0]['cells'][0]['assessed_at'],'2026-01-01')
        self.assertEqual(result['coverage'][0]['state'],'failed')
        self.assertEqual(result['assessments'][0]['state'],'completed')
        self.assertTrue(result['assessments'][0]['empty'])
        self.assertEqual(result['assessments'][1]['state'],'partial')

    def test_native_saved_page_does_not_depend_on_preview_or_source_html_renderer(self):
        text='Preserved exact source'
        payload=dict(op='cached',mode='page',title='Winter War',edition='en',wiki='wiki_en',
            source=dict(revision_id=123,lang='en',title='Winter War',sha256=hashlib.sha256(text.encode()).hexdigest()))
        saved=dict(status='ok',wikitext=text,flags=[],page_html='Old preview HTML')
        with patch('native_issues.article_topic',return_value='Q1'), \
                patch('native_issues.archived_scan',return_value=saved), \
                patch('revision_text.cached_revision',return_value=dict(wikitext=text)), \
                patch('flags_routes.cached_page_audit',return_value=saved), \
                patch('flags_routes.rendered_page_html',side_effect=AssertionError('Native uses its own parser')) as renderer:
            result=dispatch(payload)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['flags'],[])
        self.assertNotIn('page_html',result)
        self.assertEqual(saved['page_html'],'Old preview HTML')
        renderer.assert_not_called()


if __name__=='__main__':unittest.main()

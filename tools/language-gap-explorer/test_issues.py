"""Issue identity, exact evidence, navigation, and optional isolated MariaDB/SVT checks."""
import json
import os
import unittest
import uuid
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import issues
from issues_routes import evidence_view,cropped_diff
from flags_tab import RevisionRef

class IssueTests(unittest.TestCase):
    def test_language_identity_is_scoped_to_run_and_never_title(self):
        self.assertEqual(issues.language_id('run','group'),issues.language_id('run','group'))
        self.assertNotEqual(issues.language_id('run','group'),issues.language_id('other','group'))
        self.assertNotEqual(issues.language_id('run','group'),issues.identity('flags','run','group'))

    def language(self):
        return dict(id='issue',title='Compare accounts',mode='language',stamp='2025-01-01T00:00:00Z',kind='framing',label='Framing difference',context={},evidence={'evidence':[dict(lang='fi',revision=2,stamp='2024-01-01',quote='<script>untrusted</script>'),dict(lang='sv',revision=3,stamp='2024-01-01',quote='Original wording')]})

    def test_language_evidence_is_escaped_and_missing_current_edition_is_explicit(self):
        view=evidence_view(self.language(),'en')
        self.assertIn('EN Â· evidence unavailable',view['diff_html'])
        self.assertIn('&lt;script&gt;',view['diff_html'])
        self.assertNotIn('<script>',view['diff_html'])
        self.assertIn('--comparison-columns:3',view['diff_html'])
        self.assertEqual(view['sources'][0]['url'],'https://fi.wikipedia.org/w/index.php?oldid=2')

    def test_language_order_preserves_current_edition(self):
        view=evidence_view(self.language(),'sv')
        self.assertLess(view['diff_html'].index('SV Â· revision'),view['diff_html'].index('FI Â· revision'))
        self.assertEqual(view['flags'][0]['anchor_text'],'Original wording')

    def test_future_or_wrong_source_revision_fails_explicitly(self):
        for addition in [dict(stamp='2026-01-01'),dict(url='https://example.com/wrong')]:
            row=self.language();row['evidence']['evidence'][0].update(addition)
            with self.assertRaises(LookupError):evidence_view(row,'fi')

    def test_internal_conflict_is_not_presented_as_an_edit(self):
        row=dict(mode='page',context={'flag':dict(id='f',kind='OUT_OF_SYNC',title='Values differ',anchor_text='First value 1.',evidence=[dict(source='page',quote='Other value 2.')])},evidence={'ref':dict(lang='en',revision_id=2),'result':{'wikitext':'First value 1. Other value 2.'}})
        view=evidence_view(row,'en')
        self.assertIn('same revision',view['diff_html'])
        self.assertEqual(len(view['flags']),2)
        self.assertNotIn('Prior revision',view['diff_html'])

    def test_focused_edit_hunk_retains_actual_old_and_new_ranges(self):
        old='\n'.join('Line '+str(i) for i in range(40))
        new=old.replace('Line 20','Changed value 50')
        first,second,focused=cropped_diff(old,new,dict(side='new',anchor_text='Changed value 50'))
        self.assertTrue(focused);self.assertIn('Line 20',first);self.assertIn('Changed value 50',second)
        self.assertNotIn('Line 0\n',first)

    def test_review_update_requires_token_and_exact_observation(self):
        from app import app
        with app.test_client() as client,patch('issues.mark_reviewed') as update:
            self.assertEqual(client.post('/api/issues/i/review',json={'topic':'Q1','reviewed':True}).status_code,403)
            client.get('/')
            with client.session_transaction() as state:token=state['review_token']
            response=client.post('/api/issues/i/review',headers={'X-Review-Token':token},json={'topic':'Q1','reviewed':True})
            self.assertEqual(response.status_code,400);update.assert_not_called()
            update.return_value=dict(reviewed=True)
            response=client.post('/api/issues/i/review',headers={'X-Review-Token':token},json={'topic':'Q1','observation':'o','edition':'fi','reviewed':True})
            self.assertEqual(response.status_code,200);update.assert_called_once_with('Q1','i','o','fi',True)

    def test_legacy_redirect_keeps_exact_occurrence_languages_and_return_context(self):
        from app import app
        row=dict(id='o',occurrence='exact')
        with app.test_client() as client,patch('paired_history.summary',return_value={'ready':True}),patch('issues.resolve_legacy',return_value=('i',row)),patch('app.comparison_context',side_effect=AssertionError('No snapshot fallback')):
            response=client.get('/langcompare/Q1?run='+'a'*64+'&group='+'b'*64+'&stamp=2025-01-01T00:00:00Z&occurrence=exact&languages=fi&languages=sv&skyline=topic%3DQ1')
            self.assertEqual(response.status_code,302)
            self.assertIn('/article/Q1/issues/i?',response.location)
            self.assertIn('occurrence=exact',response.location)
            self.assertIn('languages=fi&languages=sv',response.location)
            self.assertIn('skyline=topic%3DQ1',response.location)

    def test_internal_issue_page_renders_shared_comment_workspace(self):
        from app import app
        row=dict(id='i',title='Internal test',mode='page',origin='flags',kind='OUT_OF_SYNC',label='Out of sync',stamp='2025-01-01',assessed_at='2026-01-01',observation='o',occurrence=None,languages=['en'],reviewed=False,observations=[],context={'flag':dict(id='f',kind='OUT_OF_SYNC',title='Values differ',anchor_text='First value 1.',evidence=[dict(source='page',quote='Other value 2.')])},evidence={'ref':dict(lang='en',revision_id=2),'result':{'wikitext':'First value 1. Other value 2.'}})
        with app.test_client() as client,patch('issues_routes.context',return_value=dict(topic='Q1',title='Synthetic test',current_lang='en',active_article_tab='issues')),patch('issues.get_observation',return_value=row):
            response=client.get('/article/Q1/issues/i?observation=o')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Within one revision',response.data)
        self.assertIn(b'First value 1.',response.data)
        self.assertIn(b'Other value 2.',response.data)
        self.assertIn(b'Mark reviewed',response.data)
        self.assertIn(b'/assets/flags/stacking.js',response.data)

    def test_storage_failure_keeps_successful_scan_pending_without_replacing_cache(self):
        import tempfile
        from pathlib import Path
        from flags_routes import save_issue_scan,pending_result
        ref=RevisionRef('en',22,'Example')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'LANGGAP_FLAGS_CACHE':directory,'LANGGAP_FIXTURES':'0'}),patch('issues.store_scan',side_effect=issues.PersistenceError('Storage offline')):
            with self.assertRaises(issues.PersistenceError):save_issue_scan(ref,dict(status='ok',flags=[]),{'topic':'Q1'},'revision')
            pending=pending_result(ref,{'topic':'Q1'},'revision')
            self.assertEqual(pending['status'],'ok');self.assertTrue(pending['_issue_assessment'])
            self.assertFalse((Path(directory)/'audits/en-22.json').exists())

@unittest.skipUnless(os.getenv('PALIMPSEST_TEST_ISSUES_DB')=='1','Opt-in isolated MariaDB/SVT integration')
class IssueDatabaseTests(unittest.TestCase):
    def setUp(self):
        from core import connect
        self.raw=connect;self.prefix='test_ui_'+uuid.uuid4().hex[:12]+'_'
        prefix=self.prefix
        class Cursor:
            def __init__(self,wrapped):self.wrapped=wrapped
            def __enter__(self):return self
            def __exit__(self,*args):return self.wrapped.__exit__(*args)
            def execute(self,sql,args=()):return self.wrapped.execute(sql.replace('unified_',prefix),args)
            def __getattr__(self,name):return getattr(self.wrapped,name)
        class DB:
            def __init__(self):self.wrapped=connect()
            def __enter__(self):self.wrapped.__enter__();return self
            def __exit__(self,*args):return self.wrapped.__exit__(*args)
            def cursor(self):return Cursor(self.wrapped.cursor())
            def __getattr__(self,name):return getattr(self.wrapped,name)
        self.patch=patch('issues.connect',DB);self.patch.start();issues.init()
    def tearDown(self):
        self.patch.stop()
        # Only this test's unique derived tables may be dropped.
        self.assertRegex(self.prefix,r'^test_ui_[a-f0-9]{12}_$')
        with self.raw() as db,db.cursor() as c:
            for name in ('native_review','review','coverage','observation','assessment','issue'):c.execute('DROP TABLE '+self.prefix+name)
    def result(self,aid='a',title='A finding'):
        return dict(status='ok',_issue_assessment=issues.identity(aid),_issue_assessed_at='2026-01-01',old_wikitext='Old value',new_wikitext='New value',flags=[dict(id='f',kind='FACT',title=title,anchor_text='New value',side='new')])
    def test_exact_job_assessment_links_preserve_older_and_successful_empty_results(self):
        ref=RevisionRef('en',22,'Synthetic test','2025-01-01',parent_id=21)
        old=self.result('exact-old');issues.store_scan('Q999999',ref,old,'revision')
        empty=self.result('exact-empty');empty['flags']=[];empty['_issue_assessed_at']='2026-02-01'
        issues.store_scan('Q999999',ref,empty,'revision')
        selected=issues.list_issues('Q999999',MultiDict({'assessment':old['_issue_assessment']}))
        self.assertEqual(selected['total'],1)
        self.assertEqual(selected['issues'][0]['assessment_id'],old['_issue_assessment'])
        clean=issues.list_issues('Q999999',MultiDict({'assessment':empty['_issue_assessment']}))
        self.assertEqual(clean['total'],0)
        self.assertEqual(clean['selected_assessment']['state'],'completed')
        self.assertEqual(clean['selected_assessment']['findings'],0)
        with self.assertRaises(LookupError):issues.list_issues('Q999998',MultiDict({'assessment':old['_issue_assessment']}))
    def test_immutable_scans_idempotence_latest_empty_set_and_system_time(self):
        ref=RevisionRef('en',22,'Synthetic test','2025-01-01',parent_id=21)
        issues.store_scan('Q999999',ref,self.result(),'revision')
        issues.store_scan('Q999999',ref,self.result(),'revision')
        first=issues.list_issues('Q999999',MultiDict())
        self.assertEqual(first['total'],1);one=first['issues'][0]
        issues.store_scan('Q999999',ref,self.result('b','Updated label'),'revision')
        history=issues.list_issues('Q999999',MultiDict({'view':'history'}))
        self.assertEqual(history['total'],2)
        original=issues.get_observation('Q999999',one['id'],one['observation'])
        self.assertEqual(original['evidence']['result']['flags'][0]['title'],'A finding')
        issues.mark_reviewed('Q999999',one['id'],one['observation'],'en',True)
        issues.mark_reviewed('Q999999',one['id'],one['observation'],'en',False)
        self.assertFalse(issues.get_observation('Q999999',one['id'],one['observation'],edition='fi')['reviewed'])
        with issues.connect() as db,db.cursor() as c:
            c.execute('SELECT COUNT(*) n FROM unified_review FOR SYSTEM_TIME ALL');self.assertEqual(c.fetchone()['n'],2)
            c.execute('SELECT COUNT(*) n FROM unified_issue FOR SYSTEM_TIME ALL');self.assertEqual(c.fetchone()['n'],2)
        with self.assertRaises(LookupError):issues.get_observation('Q999999',one['id'],'nonexistent')
        issues.store_scan('Q999999',RevisionRef('en',23,'Synthetic test','2025-02-01'),dict(status='ok',flags=[],_issue_assessment=issues.identity('empty')),'revision')
        self.assertEqual(issues.list_issues('Q999999',MultiDict())['total'],0)
        self.assertEqual(issues.list_issues('Q999999',MultiDict({'view':'history'}))['total'],2)
        with self.assertRaises(ValueError):issues.store_scan('Q999999',ref,dict(status='error',flags=[]),'revision')

    def test_history_run_preserves_detector_rows_without_mixing_language_cohorts(self):
        issues.store_scan('Q999999',RevisionRef('en',22,'Synthetic test','2025-01-01'),self.result(),'revision')
        with issues.connect() as db,db.cursor() as c:
            for run in ('one','two'):
                aid=issues.identity('assessment',run);iid=issues.language_id(run,'group');oid=issues.identity('observation',run)
                issues.put_issue(c,iid,'Q999999','language',run,'Same title in separate runs')
                c.execute('INSERT INTO unified_assessment(id,topic,mode,assessed_at,payload) VALUES(%s,%s,%s,%s,%s)',(aid,'Q999999','language','2026-01-01',json.dumps({'run':run})))
                c.execute('INSERT INTO unified_observation(id,issue_id,assessment_id,stamp,kind,languages,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(oid,iid,aid,'2025-01-01','coverage','en,fi','{}'))
        selected=issues.list_issues('Q999999',MultiDict({'view':'history','run':'one'}))
        self.assertEqual(selected['total'],2)
        self.assertEqual({r['id'] for r in selected['issues'] if r['origin']=='language'},{issues.language_id('one','group')})
        missing=issues.list_issues('Q999999',MultiDict({'view':'history','run':'unavailable','origin':'language'}))
        self.assertEqual(missing['total'],0)

    def test_native_reviews_are_wiki_edition_scoped_and_system_versioned(self):
        ref=RevisionRef('en',22,'Synthetic test','2025-01-01',parent_id=21)
        issues.store_scan('Q999999',ref,self.result(),'revision')
        one=issues.list_issues('Q999999',MultiDict())['issues'][0]
        issues.mark_reviewed('Q999999',one['id'],one['observation'],'en',True)
        self.assertFalse(issues.get_observation('Q999999',one['id'],one['observation'],review_scope='wiki_a')['reviewed'])
        with issues.connect() as db,db.cursor() as c:
            c.execute('INSERT INTO unified_native_review(wiki,observation_id,edition,reviewed,reviewer_id) VALUES(%s,%s,%s,1,12)',('wiki_a',one['observation'],'en'))
            c.execute('UPDATE unified_native_review SET reviewed=0,reviewer_id=13 WHERE wiki=%s',('wiki_a',))
            c.execute('UPDATE unified_native_review SET reviewed=1,reviewer_id=14 WHERE wiki=%s',('wiki_a',))
            c.execute('SELECT reviewer_id FROM unified_native_review FOR SYSTEM_TIME ALL ORDER BY reviewer_id');self.assertEqual([r['reviewer_id'] for r in c.fetchall()],[12,13,14])
        self.assertTrue(issues.get_observation('Q999999',one['id'],one['observation'],review_scope='wiki_a')['reviewed'])
        self.assertFalse(issues.get_observation('Q999999',one['id'],one['observation'],review_scope='wiki_b')['reviewed'])
        self.assertFalse(issues.get_observation('Q999999',one['id'],one['observation'],edition='fi',review_scope='wiki_a')['reviewed'])
        self.assertEqual(issues.list_issues('Q999999',MultiDict({'review':'reviewed'}),review_scope='wiki_a')['total'],1)
        self.assertEqual(issues.list_issues('Q999999',MultiDict({'review':'reviewed'}),review_scope='wiki_b')['total'],0)

    def test_detector_uppercase_framing_never_matches_language_classification(self):
        ref=RevisionRef('en',22,'Synthetic test','2025-01-01',parent_id=21)
        result=self.result()
        result['flags']=[dict(id='upper',kind='FRAMING',title='Wording',anchor_text='upper'),dict(id='lower',kind='framing',title='Language framing',anchor_text='lower')]
        issues.store_scan('Q999999',ref,result,'revision')
        upper=issues.list_issues('Q999999',MultiDict({'kind':'FRAMING'}))
        lower=issues.list_issues('Q999999',MultiDict({'kind':'framing'}))
        self.assertEqual(upper['total'],1);self.assertEqual(lower['total'],1)
        self.assertIn('FRAMING',upper['kinds']);self.assertIn('framing',upper['kinds'])
        self.assertEqual(upper['issues'][0]['kind'],'FRAMING')

if __name__=='__main__':unittest.main()

"""Offline behavior/route checks; these do not claim a completed live backtest."""
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import semantic_timeline as timeline
from timeline_routes import marked_diff


def fixture(lang='fi'):
    before='The treaty was signed in 1939.';after='The treaty was not signed in 1940.'
    data=timeline.changed_units(before,after)[0]
    assessment=dict(categories=['fact'],scores=dict(meaning=.95,fact=.94,framing=.1,information=.2,wording=.02),threshold=.8)
    unit=dict(id='b'*64,data=data,assessment=assessment)
    event=dict(id='a'*64,lang=lang,before_rev=1,after_rev=2,stamp='2025-07-01T12:00:00Z',
        summary='<script>source summary</script>',data=dict(gap=False),units=[unit],categories=['fact'])
    event['title']=timeline.event_title(event)
    return event


class EvidenceTests(unittest.TestCase):
    def test_exact_offsets_unicode_and_negation(self):
        before='## History\n\nSotaa ei aloitettu vuonna 1939.'
        after='## History\n\nSota aloitettiin vuonna 1940.'
        units=timeline.changed_units(before,after)
        self.assertEqual(len(units),1)
        for u in units:
            self.assertEqual(u['before'],before[u['before_start']:u['before_end']])
            self.assertEqual(u['after'],after[u['after_start']:u['after_end']])
            self.assertEqual(u['heading'],'History')

    def test_moves_and_punctuation_suppressed(self):
        self.assertEqual(timeline.changed_units('First.\n\nSecond.','Second.\n\nFirst.'),[])
        self.assertEqual(timeline.changed_units('Same text.','Same text!'),[])

    def test_inserted_paragraph_does_not_shift_replacement_alignment(self):
        before='Historically, the invasion was an embarassing failure and hurt prestige.'
        after='Historians disagree on who won.\n\nHistorically, the invasion was an embarrassing failure and hurt prestige.'
        units=timeline.changed_units(before,after)
        inserted=next(u for u in units if not u['before'])
        corrected=next(u for u in units if u['before'])
        self.assertEqual(inserted['after'],'Historians disagree on who won.')
        self.assertIn('embarassing',corrected['before'])
        self.assertIn('embarrassing',corrected['after'])

    def test_heading_changes_are_not_discarded(self):
        units=timeline.changed_units('## Alleged crimes\n\nSame prose.', '## Confirmed crimes\n\nSame prose.')
        self.assertEqual(len(units),1)
        self.assertIn('Alleged',units[0]['before'])
        self.assertIn('Confirmed',units[0]['after'])

    def test_cached_parent_timestamp_is_filled_when_metadata_arrives(self):
        calls=[]
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def cursor(self):return self
            def execute(self,*args):calls.append(args)
            def fetchone(self):return dict(text='Cached prose.',stamp='')
        with patch.object(timeline,'connect',return_value=DB()),patch.object(timeline,'fetched_revision',side_effect=AssertionError('Cache should be reused')):
            self.assertEqual(timeline.normalized_revision('en',2,'2025-01-01T00:00:00Z'),'Cached prose.')
        updates=[call for call in calls if call[0].startswith('UPDATE timeline_revision')]
        self.assertEqual(updates[0][1],('2025-01-01T00:00:00Z','en',2))

    def test_no_prose_change_is_not_an_ai_wording_assessment(self):
        row=dict(id='e',lang='en',before_rev=1,after_rev=2,stamp='2025-01-01T00:00:00Z',summary='',payload='{"gap":false}')
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def cursor(self):return self
            def execute(self,sql,*args):self.sql=sql
            def fetchall(self):return [dict(row)] if 'FROM timeline_event' in self.sql else []
            def fetchone(self):return None
        with patch.object(timeline,'connect',return_value=DB()),patch('live_api.decisions',side_effect=AssertionError('No AI needed')):
            events,_=timeline.overview()
        self.assertEqual(events[0]['categories'],['unchanged'])
        self.assertEqual(events[0]['units'],[])

    def test_deletion_and_long_insert_no_tail_lost(self):
        after=('Новое предложение. '*600)+'END_MARKER'
        units=timeline.changed_units('',after)
        self.assertEqual(''.join(u['after'] for u in units),after)
        self.assertTrue(all(len(u['after'])<=1200 for u in units))
        self.assertTrue(all(u['split_context'] for u in units))
        deleted=timeline.changed_units('Old information.','')[0]
        self.assertEqual(deleted['before'],'Old information.')
        self.assertEqual(deleted['after'],'')

    def test_threshold_overlap_and_inconclusive(self):
        self.assertEqual(timeline.categories(dict(meaning=.95,fact=.9,framing=.85,information=.9)),['fact','framing','information'])
        self.assertEqual(timeline.categories(dict(meaning=.79,fact=.99)),['inconclusive'])
        self.assertEqual(timeline.categories(dict(meaning=.1,wording=.99)),['wording'])

    def test_real_token_cap_does_not_truncate_slices(self):
        class Encoding:
            def __init__(self,text):self.ids=list(text)
        class Tokenizer:
            def encode(self,text):return Encoding(text)
        text='ä'*2500
        slices=timeline.bounded_slices(text,0,len(text),tokenizer=Tokenizer())
        self.assertEqual(''.join(text[a:b] for a,b in slices),text)
        self.assertTrue(all(b-a<=400 for a,b in slices))

    def test_title_code_and_html_escape(self):
        self.assertIn('1939 → 1940',fixture()['title'])
        old,new=marked_diff('<script>old</script>','<script>new</script>')
        self.assertNotIn('<script>',str(old)+str(new))
        self.assertIn('<del>',old);self.assertIn('<ins>',new)

    def test_time_cap(self):
        self.assertEqual(timeline.cutoff_time('2024-01-01T00:00:00Z','2025-01-01T00:00:00Z'),'2024-01-01T00:00:00Z')
        self.assertEqual(timeline.cutoff_time('2026-01-01T00:00:00Z','2025-01-01T00:00:00Z'),'2025-01-01T00:00:00Z')

    def test_future_counterpart_rejected_before_embedding(self):
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,*args):pass
            def fetchone(self):return None
        class DB(Cursor):
            def cursor(self):return Cursor()
        anchor=dict(anchor_rev=3,page_id=10,stamp='2025-06-01T00:00:00Z')
        response=dict(query=dict(pages=[dict(revisions=[dict(revid=4,timestamp='2025-07-02T00:00:00Z')])]))
        with patch.object(timeline,'event_detail',return_value=fixture()),patch.object(timeline,'editions',return_value={'en':anchor}),patch.object(timeline,'connect',return_value=DB()),patch.object(timeline,'api',return_value=response) as api:
            with self.assertRaisesRegex(ValueError,'Future'):
                timeline.compare_at_time('a'*64,'en')
            self.assertEqual(api.call_args.args[1]['rvstart'],anchor['stamp'])

    def test_budget_error_stops_and_keeps_pending(self):
        from live_api import BudgetError
        row=dict(id='u',lang='fi',payload=json.dumps(dict(before='one',after='two')))
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def cursor(self):return self
            def execute(self,*args):pass
            def fetchall(self):return [row]
        with patch.object(timeline,'connect',return_value=DB()),patch.object(timeline,'state') as state,patch('live_api.decisions',side_effect=BudgetError('ceiling')) as decisions:
            with self.assertRaises(BudgetError):timeline.classify_pending()
            self.assertEqual(decisions.call_count,1)
            self.assertEqual(state.call_args.args[0],'partial')


class RouteTests(unittest.TestCase):
    def setUp(self):
        from app import app
        self.app=app;self.client=app.test_client();self.event=fixture()

    @contextmanager
    def sources(self):
        with patch.object(timeline,'overview',return_value=([copy.deepcopy(self.event)],None)),patch.object(timeline,'editions',return_value={}),patch.object(timeline,'cached_revision',return_value=None),patch.object(timeline,'api',side_effect=AssertionError('GET fetched')),patch('live_api.decisions',side_effect=AssertionError('GET spent')):
            yield

    def test_get_no_fetch_or_paid_calls_and_four_tabs(self):
        with self.sources():
            response=self.client.get('/wiki/Q134949/timeline?lang=en')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('Semantic timeline',html)
        self.assertIn('Russian',html)
        self.assertIn('timeline-data',html)
        self.assertIn('/wiki/Q134949?lang=en',html)

    def test_direct_selected_evidence_and_ours_left(self):
        with self.sources():
            response=self.client.get('/wiki/Q134949/timeline?lang=en&event='+'a'*64)
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertLess(html.index('Your article · English'),html.index('Changed article · Finnish'))
        self.assertIn('&lt;script&gt;source summary&lt;/script&gt;',html)
        self.assertIn('Compare editions at this time',html)
        self.assertIn('English translation',html)

    def test_invalid_topic_language_and_csrf(self):
        self.assertEqual(self.client.get('/wiki/Q2606233/timeline').status_code,404)
        self.assertEqual(self.client.get('/wiki/Q134949/timeline?lang=xx').status_code,400)
        self.assertEqual(self.client.post('/wiki/Q134949/timeline/events/a/compare?lang=en').status_code,403)

    def test_comparison_explicit_post_and_local_diff(self):
        with self.client.session_transaction() as session:session['review_token']='token'
        with self.sources(),patch.object(timeline,'compare_at_time',return_value=dict(local=False,matches=[],missing=True)) as compare:
            response=self.client.post('/wiki/Q134949/timeline/events/'+'a'*64+'/compare?lang=en',data=dict(token='token'))
        self.assertEqual(response.status_code,200);compare.assert_called_once_with('a'*64,'en')


if __name__=='__main__':unittest.main()

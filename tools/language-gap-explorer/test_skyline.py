"""Skyline semantics and exact tracker handoff. No provider or database calls."""
import copy
import unittest
from unittest.mock import patch, MagicMock
import json
from urllib.parse import urlsplit,parse_qs
from werkzeug.datastructures import MultiDict

from skyline import aggregate, phases_at, occurrence_choice, left_language, tracker_context,assessment_warning
from explore_preview import app as preview

RUN='a'*64
GROUP='b'*64
STAMP='2025-07-29T18:20:39Z'


def source(lang,value):
    return dict(lang=lang,quote=value,section='Peace negotiations',revision=4,stamp='2025-07-20T00:00:00Z',
                url=f'https://{lang}.wikipedia.org/w/index.php?oldid=4',highlights=[])


def fixture():
    pairs=[dict(id='c'*64,kind='coverage',evidence=[dict(lang='en'),dict(lang='fi')]),
           dict(id='d'*64,kind='framing',evidence=[dict(lang='fi'),dict(lang='sv')])]
    phase=dict(start=STAMP,end=STAMP,kind='framing',pairs=pairs,reason='Stored criterion',action='Review citations')
    return dict(run=RUN,topic=dict(id='Q134949',title='Winter War',languages=['en','fi','sv']),bounds=['2020-01-01T00:00:00Z',STAMP],
                asOf=STAMP,rows=[dict(id=GROUP,title='Stored question',phases=[phase])],
                observations=[dict(stamp='2020-01-01T00:00:00Z',state='unknown'),dict(stamp=STAMP,state='complete')],progress=dict(stage='ready'))


class SkylineTests(unittest.TestCase):
    def test_incompatible_model_signals_stay_visible_without_relabeling(self):
        occurrence=dict(kind='contradiction',scores=dict(compatible=dict(probability=1.0)))
        self.assertIn('uncertain',assessment_warning(occurrence))
        self.assertEqual(occurrence['kind'],'contradiction')
        self.assertEqual(assessment_warning(dict(kind='framing',scores=occurrence['scores'])),'')

    def test_one_question_not_passage_or_pair_counts(self):
        data=fixture();data['rows'].append(copy.deepcopy(data['rows'][0]))
        result=aggregate(data,['en','fi','sv'])['observations'][-1]
        self.assertEqual(result['total'],1)
        self.assertEqual(result['counts'],dict(coverage=0,framing=1,contradiction=0))

    def test_language_order_does_not_change_counts(self):
        a=aggregate(fixture(),['en','fi','sv'])['observations']
        b=aggregate(fixture(),['sv','en','fi'])['observations']
        self.assertEqual(a,b)

    def test_subset_does_not_inherit_another_pairs_category(self):
        result=aggregate(fixture(),['en','fi'])['observations'][-1]
        self.assertEqual(result['counts']['coverage'],1)
        self.assertEqual(result['counts']['framing'],0)

    def test_unknown_and_observed_zero_have_different_states(self):
        data=fixture();data['rows']=[]
        result=aggregate(data,['en','fi','sv'])['observations']
        self.assertEqual([o['state'] for o in result],['unknown','complete'])
        self.assertTrue(all(o['total']==0 for o in result))

    def test_category_support_wins_over_english_preference(self):
        occurrences=[dict(id='c'*64,kind='coverage',evidence=[source('en','A'),source('fi','B')]),
                     dict(id='d'*64,kind='framing',evidence=[source('fi','B'),source('sv','C')])]
        chosen=occurrence_choice(occurrences,['en','fi','sv'],'en','framing')
        self.assertEqual(chosen['id'],'d'*64)
        self.assertEqual(left_language(chosen,'en'),'fi')

    def test_tracker_preserves_exact_scope_and_escapes_source(self):
        occurrence=dict(id='d'*64,kind='framing',question='cause',evidence=[source('fi','<script>source</script>'),source('sv','Swedish source')])
        args=MultiDict([('topic','Q134949'),('run',RUN),('group',GROUP),('stamp',STAMP),('lang','en'),
                       ('languages','en'),('languages','fi'),('languages','sv'),('skyline','topic=Q134949&kind=framing')])
        with patch('paired_history.summary',return_value=fixture()) as summary,patch('paired_history.detail',return_value=dict(occurrences=[occurrence])),patch('paired_history.decisions',side_effect=AssertionError('read must not spend')):
            context=tracker_context('Q134949',args)
        summary.assert_called_once_with('Q134949',['en','fi','sv'],run=RUN)
        self.assertEqual(context['current_lang'],'fi')
        self.assertEqual(context['historical_back'],'/explore?topic=Q134949&kind=framing')
        self.assertEqual(context['historical_evidence'][0]['quote'],'<script>source</script>')
        self.assertIn('&lt;script&gt;',str(context['historical_evidence'][0]['quote_html']))

    def test_featured_collection_is_read_only(self):
        with patch('article_pipeline.showcase_articles',return_value=[dict(id='Q134949',status='ready',count=135)]),patch('article_pipeline.enqueue',side_effect=AssertionError('GET must not prepare')):
            with preview.test_client() as client:response=client.get('/explore/api/showcase')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['articles'][0]['count'],135)

    def test_missing_run_never_falls_back_to_snapshot(self):
        args=MultiDict([('topic','Q134949'),('run',RUN),('group',GROUP),('stamp',STAMP)])
        with patch('paired_history.summary',return_value=None):
            with self.assertRaises(LookupError):tracker_context('Q134949',args)

    def test_overview_endpoint_only_reads_and_omits_private_ledger(self):
        data=fixture();data['cost']={'private':123}
        with patch('paired_history.summary',return_value=data),patch('paired_history.decisions',side_effect=AssertionError('read must not spend')):
            with preview.test_client() as client:
                response=client.get('/explore/api/skyline?topic=Q134949&languages=en&languages=fi&languages=sv')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('cost',response.get_json())

    def test_invalid_scope_never_queries_database(self):
        with patch('paired_history.summary') as read:
            with preview.test_client() as client:
                self.assertEqual(client.get('/explore/api/skyline?languages=en&languages=ru').status_code,400)
            read.assert_not_called()

    def test_more_than_six_questions_remain_available(self):
        data=fixture();data['rows']=[dict(id=f'{i:064x}',title='Question',phases=copy.deepcopy(data['rows'][0]['phases'])) for i in range(80)]
        self.assertEqual(aggregate(data,['en','fi','sv'])['observations'][-1]['total'],80)

    def test_question_link_carries_run_stamp_and_actual_pair(self):
        from skyline import question_page
        occurrence=dict(id='d'*64,kind='framing',question='cause',evidence=[source('fi','Finnish'),source('sv','Swedish')])
        with patch('paired_history.detail',return_value=dict(occurrences=[occurrence])):
            result=question_page(fixture(),['en','fi','sv'],STAMP,kind='framing',back_query='kind=framing')
        target=parse_qs(urlsplit(result['questions'][0]['href']).query)
        self.assertEqual(target['run'],[RUN]);self.assertEqual(target['stamp'],[STAMP]);self.assertEqual(target['lang'],['fi'])
        self.assertEqual(target['skyline'],['kind=framing'])

    def test_future_source_is_rejected_by_tracker(self):
        occurrence=dict(id='d'*64,kind='framing',question='cause',evidence=[source('fi','A'),source('sv','B')])
        occurrence['evidence'][0]['stamp']='2026-01-01T00:00:00Z'
        args=MultiDict([('topic','Q134949'),('run',RUN),('group',GROUP),('stamp',STAMP)])
        with patch('paired_history.summary',return_value=fixture()),patch('paired_history.detail',return_value=dict(occurrences=[occurrence])):
            with self.assertRaises(LookupError):tracker_context('Q134949',args)

    def test_completed_empty_checkpoint_is_not_unobserved(self):
        from paired_history import summary
        data=fixture();data['rows']=[];data['progress']=dict(stage='classifying',completed_checkpoints=1)
        window=['2020-01-01T00:00:00Z','2021-01-01T00:00:00Z',STAMP]
        db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value=[dict(summary=json.dumps(data),configuration=json.dumps(dict(window=window)))]
        with patch('paired_history.connect',return_value=db):result=summary('Q134949',['en','fi','sv'])
        self.assertEqual([o['state'] for o in result['observations']],['unknown','unknown','complete'])

    def test_missing_historical_route_does_not_call_snapshot_pipeline(self):
        from app import app
        with patch('paired_history.summary',return_value=None),patch('pipeline.latest',side_effect=AssertionError('Must not fall back to snapshot')):
            with app.test_client() as client:
                response=client.get('/langcompare/Q134949?run='+RUN+'&group='+GROUP+'&stamp='+STAMP)
        self.assertEqual(response.status_code,404)
        self.assertIn(b'not substituted',response.data)


if __name__=='__main__':unittest.main()

"""Historical invariants, classification gates and read-side boundaries. No paid calls."""
import copy
import unittest
from unittest.mock import patch
from historical_divergence import schedule,excerpts,relation_kind,aggregate,scope_result
from explore_preview import app
from live_api import within_budget


class HistoricalTests(unittest.TestCase):
    def manifest(self):
        return dict(anchors={'en':{'stamp':'2025-01-04T00:00:00Z'},'fi':{'stamp':'2025-01-03T00:00:00Z'}},history={
          'en':[{'revid':1,'timestamp':'2025-01-01T00:00:00Z'},{'revid':2,'timestamp':'2025-01-03T12:00:00Z'},{'revid':3,'timestamp':'2025-01-04T00:00:00Z'}],
          'fi':[{'revid':4,'timestamp':'2025-01-02T00:00:00Z'},{'revid':5,'timestamp':'2025-01-03T00:00:00Z'}]})

    def test_future_and_anchor_cutoff(self):
        m=self.manifest();window=schedule(m,['en','fi'],20)
        self.assertEqual([p['stamp'] for p in window],['2025-01-02T00:00:00Z','2025-01-03T00:00:00Z'])
        for point in window:
            self.assertEqual(point['revisions']['en']['revid'],1)
            self.assertTrue(all(r['timestamp']<=point['stamp'] for r in point['revisions'].values()))

    def test_every_enumerated_event_in_chosen_window(self):
        m=self.manifest();m['anchors']['fi']['stamp']='2025-01-04T00:00:00Z'
        window=schedule(m,['en','fi'],3)
        self.assertEqual(len(window),3)
        self.assertIn('2025-01-03T12:00:00Z',[x['stamp'] for x in window])

    def test_exact_excerpt_offsets(self):
        text='  The first sentence has enough text to identify the proposition correctly. Another complete sentence can give important context as well.'
        result=excerpts([dict(text=text,heading='History',start_offset=10,end_offset=10+len(text),similarity=.9)])
        full=' '*10+text
        self.assertGreater(len(result),0)
        for e in result:self.assertEqual(full[e['start']:e['end']],e['quote'])

    def test_contradiction_needs_separate_scope_and_conflict_support(self):
        value=dict(category=dict(choice='contradiction',confidence=.99),incompatible=dict(probability=.95),same_scope=dict(probability=.4))
        self.assertEqual(relation_kind(value),'uncertain')
        value['same_scope']['probability']=.9
        self.assertEqual(relation_kind(value),'contradiction')
        value['category']['type']='refusal';value['category'].pop('choice')
        self.assertEqual(relation_kind(value),'uncertain')

    def test_language_subset_does_not_inherit_third_edition_conflict(self):
        relations={'en_fi':dict(kind='aligned'),'en_ru':dict(kind='contradiction'),'fi_ru':dict(kind='framing')}
        self.assertEqual(aggregate(relations,['en','fi']),'aligned')
        self.assertEqual(aggregate(relations,['en','ru']),'contradiction')

    def test_scoping_removes_third_edition_reason_and_highlights(self):
        phase=dict(evidence=[dict(lang=l,quote='source',highlights=[dict(start=0,end=1)]) for l in ('en','fi','ru')],
            relations={'en_fi':dict(kind='aligned',reason='compatible'),'en_ru':dict(kind='contradiction',reason='opposite_assertions')})
        result=dict(topic={},rows=[dict(phases=[phase])])
        scoped=scope_result(result,['en','fi'])['rows'][0]['phases'][0]
        self.assertEqual(scoped['kind'],'aligned')
        self.assertNotIn('incompatible',scoped['reason'])
        self.assertTrue(all('highlights' not in e for e in scoped['evidence']))

    def test_historical_get_is_read_only(self):
        fixture=dict(mode='historical',rows=[],bounds=['2025-01-01','2025-01-02'])
        with patch('paired_history.summary',return_value=fixture) as read,patch('paired_history.decisions',side_effect=AssertionError('GET must not spend')):
            with app.test_client() as client:response=client.get('/explore/api/history?topic=Q134949&languages=en&languages=fi')
        self.assertEqual(response.status_code,200)
        read.assert_called_once_with('Q134949',['en','fi'])

    def test_bad_topic_or_language_is_not_queried(self):
        with patch('paired_history.summary') as read:
            with app.test_client() as client:
                self.assertEqual(client.get('/explore/api/history?topic=Q1&languages=en&languages=xx').status_code,400)
            read.assert_not_called()

    def test_removed_cap_and_optional_configuration(self):
        with patch.dict('os.environ',{'NEOWIKI_API_TOTAL_LIMIT_USD':''}):
            self.assertTrue(within_budget(100,1))
            self.assertFalse(within_budget(0,-1))
            self.assertFalse(within_budget(float('nan'),1))
        self.assertFalse(within_budget(9.99,.02,limit=10))


if __name__=='__main__':unittest.main()

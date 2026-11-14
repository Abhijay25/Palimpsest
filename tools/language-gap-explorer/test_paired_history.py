"""Semantic-row invariants and cold-read boundaries, without network or paid calls."""
import copy
import json
import unittest
from unittest.mock import patch,MagicMock

from paired_history import build_rows,scope_summary,classify,detail,assess
from explore_preview import app


def occurrence(identity,topic,stamp,kind='coverage',languages=('en','fi')):
    return dict(id=identity,topic_id=topic,stamp=stamp,kind=kind,
                topic=json.dumps(dict(title='What caused this event?')),
                payload=json.dumps(dict(sampled=False,evidence=[dict(lang=l,revision=i+1) for i,l in enumerate(languages)])))


class PairedHistoryTests(unittest.TestCase):
    def test_parallel_batches_prioritize_matches_and_publish_incremental_results(self):
        pairs={str(i):dict(id=str(i),similarity=i/32) for i in range(32)}
        database=MagicMock();cursor=database.__enter__.return_value.cursor.return_value.__enter__.return_value;cursor.fetchall.return_value=[]
        batches=[];progress=[]
        def fake_batch(batch):
            batches.append([p['id'] for p in batch])
            return {p['id']:dict(kind='coverage') for p in batch}
        with patch('paired_history.connect',return_value=database),patch('paired_history.WORKERS',1),patch('paired_history.verdict_batch',side_effect=fake_batch):
            result=assess(pairs,lambda done,total,known:progress.append((done,total,len(known))))
        self.assertEqual(len(result),32)
        self.assertEqual(batches[0][0],'31')
        self.assertEqual([len(b) for b in batches],[16,16])
        self.assertEqual(progress,[(16,32,16),(32,32,32)])

    def test_repeated_occurrences_and_languages_make_one_row(self):
        dates=['2020-01-01T00:00:00Z','2021-01-01T00:00:00Z']
        source=[occurrence('a','one-question',dates[0]),
                occurrence('b','one-question',dates[0],languages=('fi','ru')),
                occurrence('c','one-question',dates[1],'contradiction')]
        rows=build_rows('run',dict(checkpoints=dates),source)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0]['phases']),2)
        self.assertEqual(rows[0]['phases'][0]['occurrences'],['a','b'])
        self.assertEqual(rows[0]['languages'],['en','fi','ru'])
        self.assertEqual(rows[0]['phases'][1]['kind'],'contradiction')
        self.assertFalse(rows[0]['phases'][0]['detail_ready'])
        self.assertNotIn('quote',json.dumps(rows))

    def test_independent_questions_are_not_capped_at_six(self):
        stamp='2025-01-01T00:00:00Z'
        source=[occurrence(str(i),'question-'+str(i),stamp) for i in range(80)]
        self.assertEqual(len(build_rows('run',dict(checkpoints=[stamp]),source)),80)

    def test_pair_filter_cannot_inherit_third_edition_conflict(self):
        stamp='2025-01-01T00:00:00Z'
        source=[occurrence('a','q',stamp,'coverage'),occurrence('b','q',stamp,'contradiction',('en','ru')),
                occurrence('c','foreign-only',stamp,'framing',('fi','ru'))]
        data=dict(rows=build_rows('run',dict(checkpoints=[stamp]),source))
        scoped=scope_summary(copy.deepcopy(data),['en','fi'])
        self.assertEqual(len(scoped['rows']),1)
        phase=scoped['rows'][0]['phases'][0]
        self.assertEqual(phase['kind'],'coverage')
        self.assertEqual(phase['occurrences'],['a'])
        self.assertEqual([e['lang'] for e in phase['evidence']],['en','fi'])
        self.assertEqual(scope_summary(copy.deepcopy(data),['en','ru'])['rows'][0]['phases'][0]['kind'],'contradiction')

    def test_retrieval_failure_is_never_called_missing_information(self):
        scores={k:dict(probability=v) for k,v in dict(related=.3,coverage=.99,contradiction=.99,same_scope=.99).items()}
        self.assertEqual(classify(scores),'retrieval_failure')
        scores['related']['probability']=.95;scores['same_scope']['probability']=.4
        self.assertEqual(classify(scores),'coverage')
        scores['same_scope']['probability']=.9
        self.assertEqual(classify(scores),'contradiction')
        self.assertEqual(classify({}),'unassessed')

    def test_detail_reads_exact_occurrences_and_scopes_language_pair(self):
        stored=[dict(id='stored-id',payload=json.dumps(dict(id='legacy-id',kind='coverage',evidence=[dict(lang='en',quote='Exact 2000.'),dict(lang='fi',quote='1999.')]))) ]
        database=MagicMock();cursor=database.__enter__.return_value.cursor.return_value.__enter__.return_value;cursor.fetchall.return_value=stored
        with patch('paired_history.connect',return_value=database),patch('paired_history.decisions',side_effect=AssertionError('read must not spend')):
            result=detail('run','group','stamp',['en','fi'])
            self.assertEqual(result['occurrences'][0]['id'],'stored-id')
            self.assertEqual(result['evidence'][0]['quote'],'Exact 2000.')
            self.assertIsNone(detail('run','group','stamp',['en','ru']))

    def test_source_route_is_read_only_and_enrichment_requires_csrf(self):
        query='run='+'a'*64+'&group='+'b'*64+'&stamp=2025-01-01T00:00:00Z&languages=en&languages=fi'
        with patch('paired_history.detail',return_value=dict(occurrences=[])) as read,patch('paired_history.decisions',side_effect=AssertionError('GET must not spend')):
            with app.test_client() as client:
                self.assertEqual(client.get('/explore/api/details?'+query).status_code,200)
                self.assertEqual(client.post('/explore/api/enrich',json={}).status_code,403)
                self.assertEqual(client.get('/explore/api/details?'+query+'&languages=xx').status_code,400)
            read.assert_called_once_with('a'*64,'b'*64,'2025-01-01T00:00:00Z',languages=['en','fi'])


if __name__=='__main__':unittest.main()

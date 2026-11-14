import copy
import unittest
from unittest.mock import patch,MagicMock
from pymysql.err import ProgrammingError
import question_titles as T


def packet():
    return dict(article_id='Q1',article_title='Winter War',group_id='a'*64,display_lang='en',
        fallback='Losses · What was the scale?',evidence=[dict(id='x:0',lang='fi',text='Suomen sotilaita kuoli 25000.',revision=12,vector_id='b'*64)])


def candidate():
    return dict(question='How many Finnish soldiers died in the Winter War?',
        scope=dict(subject='Finnish soldiers',event='Winter War',time='',quantity='deaths'),
        source_ids=['x:0'],mixed_scope=False)


class QuestionTitleTests(unittest.TestCase):
    def test_specific_multilingual_question_validates_without_english_source(self):
        self.assertIsNone(T.validate(candidate(),packet()))

    def test_missing_source_is_rejected(self):
        value=candidate();value['source_ids']=['invented']
        self.assertIn('missing',T.validate(value,packet()))

    def test_generic_category_is_not_a_specific_question(self):
        value=candidate();value['question']='Which information is included?'
        self.assertIn('generic',T.validate(value,packet()))

    def test_invented_number_is_rejected(self):
        value=candidate();value['question']='Did 999 Finnish soldiers die?'
        self.assertIn('unsupported number',T.validate(value,packet()))

    def test_mixed_scope_is_review_needed(self):
        value=candidate();value['mixed_scope']=True
        self.assertIn('multiple',T.validate(value,packet()))

    def test_cache_identity_is_article_scoped(self):
        other=packet();other['article_id']='Q2'
        self.assertNotEqual(T.identity(packet())[0],T.identity(other)[0])

    def test_schema_read_missing_table_never_generates(self):
        with patch('question_titles.connect',side_effect=ProgrammingError(1146,'missing')),patch('question_titles.structured') as generate:
            self.assertEqual(T.labels('Q1',['a'*64]),{})
            generate.assert_not_called()

    def test_grounding_gate_accepts_only_supported_title(self):
        value=candidate();value['group_id']='a'*64
        with patch('question_titles.structured',return_value={'questions':[value]}),patch('question_titles.decisions',return_value={'grounded_0':{'probability':.95}}),patch('question_titles.write_result') as write:
            T.name_batch([packet()])
        self.assertEqual(write.call_args.args[1],'accepted')

    def test_low_grounding_is_provisional(self):
        value=candidate();value['group_id']='a'*64
        with patch('question_titles.structured',return_value={'questions':[value]}),patch('question_titles.decisions',return_value={'grounded_0':{'probability':.5}}),patch('question_titles.write_result') as write:
            T.name_batch([packet()])
        self.assertEqual(write.call_args.args[1],'provisional')

    def test_generation_failure_does_not_fabricate_title(self):
        with patch('question_titles.structured',side_effect=RuntimeError()),patch('question_titles.write_result') as write:
            T.name_batch([packet()])
        self.assertEqual(write.call_args.args[1],'failed')

    def test_two_same_worded_questions_keep_distinct_ids(self):
        other=packet();other['group_id']='b'*64
        self.assertNotEqual(T.identity(packet())[0],T.identity(other)[0])

    def test_stage_publishes_counts_without_provider_calls(self):
        with patch('question_titles._stage',return_value=([packet()],{'batch':[packet()]},set(),1)),patch('question_titles.structured') as generate:
            self.assertEqual(T.stage('Q1'),dict(topic='Q1',groups=1,pending_batches=1,new=1))
            generate.assert_not_called()

    def test_empty_worker_queue_never_calls_provider(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
        with patch('question_titles.init'),patch('question_titles.connect',return_value=db),patch('question_titles.structured') as generate:
            self.assertEqual(T.worker(once=True),[])
            generate.assert_not_called()

    def test_pending_reservation_cannot_downgrade_terminal_title(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        with patch('question_titles.connect',return_value=db):T.write_result(packet(),'pending')
        sql=cursor.execute.call_args.args[0]
        self.assertTrue(sql.startswith('INSERT IGNORE INTO'))
        self.assertNotIn('ON DUPLICATE KEY UPDATE',sql)

    def test_queue_consumer_does_not_discover_unqueued_runs(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={'locked':1};cursor.fetchall.return_value=[]
        with patch('question_titles.connect',return_value=db),patch('question_titles._run_batches'),patch('question_titles.representative_packets') as discover:
            self.assertEqual(T.consume_queued('Q1'),dict(topic='Q1',groups=0))
            discover.assert_not_called()


if __name__=='__main__':unittest.main()

"""Naming is the sole permitted generative stage; cached calls never use slots."""
import unittest
from unittest.mock import MagicMock,patch
from live_api import call,APIError,provider_slot


class NamingGateTests(unittest.TestCase):
    def test_other_generation_stages_stay_disabled(self):
        with patch('live_api.connect') as db:
            for endpoint,stage in [('responses','summarize'),('responses','decisions'),('chat/completions','question_titles')]:
                with self.assertRaises(APIError):call(endpoint,{},stage)
            db.assert_not_called()

    def test_title_generation_reuses_completed_request_without_network(self):
        db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[{'locked':1},{'status':'done','result':'{"cached":true}'}]
        with patch('live_api.connect',return_value=db),patch('live_api.requests.post') as post,patch('live_api.provider_slot') as slots:
            self.assertEqual(call('responses',{'model':'test'},'question_titles'),{'cached':True})
        post.assert_not_called();slots.assert_not_called()

    def test_title_and_provider_locks_release_after_failure(self):
        db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={'locked':1}
        with patch('live_api.connect',return_value=db):
            with self.assertRaisesRegex(RuntimeError,'test'):
                with provider_slot('question_titles'):raise RuntimeError('test')
        acquired=[c.args[1][0] for c in cursor.execute.call_args_list if 'GET_LOCK' in c.args[0]]
        released=[c.args[1][0] for c in cursor.execute.call_args_list if 'RELEASE_LOCK' in c.args[0]]
        self.assertEqual(acquired,['neowiki_title_worker_0','neowiki_provider_worker_0'])
        self.assertEqual(released,list(reversed(acquired)))

    def test_naming_reserves_room_for_reasoning_and_structured_output(self):
        from live_api import structured
        result={'status':'completed','output':[{'content':[{'type':'output_text','text':'{"questions":[]}'}]}]}
        with patch('live_api.call',return_value=result) as request:
            self.assertEqual(structured('Name questions',{}, {},'question_titles'),{'questions':[]})
        payload=request.call_args.args[1]
        self.assertEqual(payload['max_output_tokens'],8192)
        self.assertEqual(payload['reasoning'],{'effort':'low'})


if __name__=='__main__':unittest.main()

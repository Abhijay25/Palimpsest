import unittest
from unittest.mock import patch
from core import connect
from pipeline import init,split_article,enqueue,latest
from prepare import embedding_model
from live_api import BudgetError,APIError,call

class PipelineChecks(unittest.TestCase):
    def test_review_queue_excludes_equivalence_and_counts_uncertainty(self):
        from pipeline import review_candidates
        base={'evidence':[{'lang':'en','quote':'A fact.'},{'lang':'fi','quote':'A source.'}]}
        same=dict(base,id='same',category='same')
        conflict=dict(base,id='conflict',category='conflict')
        uncertain=dict(base,id='uncertain',category='uncertain')
        visible,counts=review_candidates([same,conflict,dict(conflict,id='duplicate'),uncertain])
        self.assertEqual([f['category'] for f in visible],['conflict','uncertain'])
        self.assertEqual(counts,{'equivalent':1,'uncertain':1,'actionable':1,'exact_duplicates':1})
    def test_model_reuse_and_existing_registration(self):
        first=embedding_model()
        self.assertIs(first,embedding_model())
        # Model registration outlives our instance cache. Reloading an instance
        # must also work when the custom model is already registered globally.
        embedding_model.cache_clear()
        second=embedding_model()
        self.assertEqual(len(next(second.embed(['query: multilingual test']))),384)
        self.assertIs(second,embedding_model())
    def test_budget_ceiling(self):
        from live_api import within_budget
        self.assertTrue(within_budget(9,.5))
        self.assertFalse(within_budget(9.99,.02,limit=10))
        self.assertTrue(within_budget(10,.001))
        self.assertFalse(within_budget(0,-1))
    @classmethod
    def setUpClass(cls):
        init(); cls.model=embedding_model()

    def test_split_exact_offsets_and_no_truncation(self):
        text='# Sample\nA first paragraph.\n\n## History\n'+('This sentence describes a historical event. '*300)+'THE FINAL WORD.'
        a={'lang':'en','rev_id':1,'text':text}
        parts=list(split_article(a,self.model.model.tokenizer))
        self.assertIn('THE FINAL WORD.',parts[-1]['text'])
        for p in parts:
            self.assertEqual(p['text'],text[p['start']:p['end']])
            self.assertLessEqual(len(self.model.model.tokenizer.encode(p['text']).ids),402)

    def test_single_language_not_reviewable(self):
        with patch('pipeline.articles',return_value={'en':{'rev_id':1}}):
            with self.assertRaises(ValueError): enqueue('Q33')

    def test_reads_do_not_call_api_and_post_requires_token(self):
        from app import app
        with patch('live_api.requests.post',side_effect=AssertionError('Page reads cannot spend money')):
            client=app.test_client()
            self.assertEqual(client.get('/langcompare/Q2606233').status_code,200)
            self.assertEqual(client.get('/reviews/Q2606233/status').status_code,200)
            self.assertEqual(client.post('/reviews/Q2606233').status_code,403)

if __name__=='__main__': unittest.main(verbosity=2)

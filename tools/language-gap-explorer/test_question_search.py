import json
import unittest
from unittest.mock import MagicMock,patch
from pymysql.err import ProgrammingError
import question_search as S


class QuestionSearchTests(unittest.TestCase):
    def test_selected_language_vectors_only(self):
        row=dict(group_id='a',title='Who initiated the invasion?',evidence=json.dumps([
            dict(lang='en',text='English evidence',vector_id='en'),
            dict(lang='sv',text='Swedish evidence',vector_id='sv')]))
        result=S.scoped_document(row,['en','fi'])
        self.assertEqual(result['_vectors'],['en'])
        self.assertNotIn('Swedish',result['text'])

    def test_fusion_keeps_keyword_and_semantic_results(self):
        result=S.fuse({'a':2},{'a':.75,'b':.9})
        self.assertEqual(result[0]['id'],'a');self.assertEqual({r['id'] for r in result},{'a','b'})

    def test_empty_scope_does_not_query_or_embed(self):
        with patch('question_search.connect') as db:
            self.assertEqual(S.search('Q1',['en','fi'],[],'peace','hybrid')['matches'],[])
            db.assert_not_called()

    def test_missing_index_is_explicit(self):
        with patch('question_search.connect',side_effect=ProgrammingError(1146,'missing')):
            result=S.search('Q1',['en','fi'],['a'],'peace')
        self.assertIn('not been prepared',result['warning'])

    def test_keyword_mode_never_embeds(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[
            dict(group_id='a',title='Peace negotiations',evidence='[]',lexical=1)]
        with patch('question_search.connect',return_value=db),patch('heatmap.semantic_scores') as semantic:
            result=S.search('Q1',['en','fi'],['a'],'peace')
        self.assertEqual(result['matches'][0]['id'],'a');semantic.assert_not_called()

    def test_semantic_failure_keeps_keyword_results(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[
            dict(group_id='a',title='Peace negotiations',evidence='[]',lexical=1)]
        with patch('question_search.connect',return_value=db),patch('heatmap.semantic_scores',side_effect=RuntimeError()):
            result=S.search('Q1',['en','fi'],['a'],'peace','hybrid')
        self.assertEqual(result['mode'],'keyword');self.assertEqual(len(result['matches']),1)

    def test_normalization_keeps_multilingual_tokens(self):
        self.assertEqual(S.normalized_tokens('Mänttä Åbo'),['mantta','abo'])

    def test_common_war_word_does_not_match_every_question(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[
            dict(group_id='a',title='Why did the war start?',evidence='[]',lexical=2),
            dict(group_id='b',title='How did the war end?',evidence='[]',lexical=1)]
        with patch('question_search.connect',return_value=db):
            result=S.search('Q1',['en','fi'],['a','b'],'who did start the war')
        self.assertEqual([r['id'] for r in result['matches']],['a'])

    def test_keyword_typeahead_uses_prepared_terms_without_source_text(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[
            dict(group_id='a',title='Peace talks',terms=json.dumps({'en':['negotiations']}),vectors=json.dumps({'en':['v']}),lexical=1)]
        with patch('question_search.connect',return_value=db):
            result=S.search('Q1',['en','fi'],['a'],'negot')
        self.assertEqual(result['matches'][0]['id'],'a')


if __name__=='__main__':unittest.main()

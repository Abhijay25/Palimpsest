"""Matrix scope, hybrid-search fallbacks and exact historical selection."""
import copy
import unittest
from unittest.mock import patch,MagicMock
from urllib.parse import urlsplit,parse_qs
from heatmap import catalog,public_catalog,hybrid_search,lexical_scores,cell_detail,_catalogs
from test_skyline import fixture,source,GROUP,STAMP
from explore_preview import app


class HeatmapTests(unittest.TestCase):
    def setUp(self):
        _catalogs.clear()

    def stored(self):
        return dict(id='d'*64,kind='framing',question='cause',evidence=[source('fi','Finnish source'),source('sv','Swedish source')])

    def test_catalog_counts_one_question_across_pairs(self):
        db=MagicMock();cursor=db.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value=[]
        with patch('core.connect',return_value=db):result=public_catalog(fixture(),['en','fi','sv'])
        self.assertEqual(len(result['rows']),1)
        cell=result['rows'][0]['cells'][0]
        self.assertEqual(cell['kind'],'framing');self.assertEqual(cell['occurrences'],2)
        self.assertEqual(cell['pair_kinds'],[dict(pair='EN–FI',kind='coverage'),dict(pair='FI–SV',kind='framing')])
        self.assertNotIn('_text',result['rows'][0])

    def test_pair_scope_does_not_inherit_framing(self):
        db=MagicMock();db.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
        with patch('core.connect',return_value=db):result=public_catalog(fixture(),['en','fi'])
        self.assertEqual(result['rows'][0]['cells'][0]['kind'],'coverage')

    def test_lexical_search_uses_source_evidence(self):
        rows=[dict(id='a',_text='Finnish account describes peace negotiations'),dict(id='b',_text='Naval losses and military strength')]
        self.assertGreater(lexical_scores(rows,'peace negotiations')['a'],0)
        self.assertNotIn('b',lexical_scores(rows,'peace negotiations'))

    def test_hybrid_merges_keyword_and_semantic_matches(self):
        rows=[dict(id='a',_text='peace negotiations'),dict(id='b',_text='diplomatic discussions')]
        with patch('heatmap.semantic_scores',return_value={'a':.75,'b':.9}):result=hybrid_search(rows,'peace')
        self.assertEqual(result['mode'],'hybrid');self.assertEqual({m['id'] for m in result['matches']},{'a','b'})
        self.assertEqual(result['matches'][0]['id'],'a')

    def test_unavailable_semantic_model_is_honest_keyword_fallback(self):
        with patch('heatmap.semantic_scores',side_effect=RuntimeError('offline')):
            result=hybrid_search([dict(id='a',_text='peace negotiations')],'peace')
        self.assertEqual(result['mode'],'keywords');self.assertIn('unavailable',result['warning'])
        self.assertEqual(len(result['matches']),1)

    def test_cell_keeps_pair_and_exact_occurrence(self):
        rows=[dict(id=GROUP,cells=[dict(stamp=STAMP,pair_kinds=[dict(pair='EN–FI',kind='coverage'),dict(pair='FI–SV',kind='framing')])])]
        with patch('heatmap.catalog',return_value=dict(rows=rows)),patch('paired_history.detail',return_value=dict(occurrences=[self.stored()])):
            result=cell_detail(fixture(),['en','fi','sv'],GROUP,STAMP,'en','sort=controversial','FI–SV','framing')
        self.assertEqual(result['destination'],'FI ↔ SV');self.assertEqual(result['kind'],'framing')
        q=parse_qs(urlsplit(result['href']).query)
        self.assertEqual(q['occurrence'],['d'*64]);self.assertEqual(q['skyline'],['sort=controversial'])

    def test_filtered_category_cannot_fall_back_to_different_pair(self):
        rows=[dict(id=GROUP,cells=[dict(stamp=STAMP,pair_kinds=[dict(pair='EN–FI',kind='coverage')])])]
        with patch('heatmap.catalog',return_value=dict(rows=rows)):
            with self.assertRaises(LookupError):cell_detail(fixture(),['en','fi','sv'],GROUP,STAMP,'en','','EN–FI','framing')

    def test_explicit_occurrence_preserves_weaker_category_in_same_pair(self):
        rows=[dict(id=GROUP,cells=[dict(stamp=STAMP,pair_kinds=[dict(pair='FI–SV',kind='framing')])])]
        weaker=self.stored();weaker.update(id='e'*64,kind='coverage')
        with patch('heatmap.catalog',return_value=dict(rows=rows)),patch('paired_history.detail',return_value=dict(occurrences=[self.stored(),weaker])):
            result=cell_detail(fixture(),['en','fi','sv'],GROUP,STAMP,'fi','','FI–SV','coverage','e'*64)
            self.assertEqual(result['occurrence'],'e'*64);self.assertEqual(result['kind'],'coverage')
            with self.assertRaises(LookupError):cell_detail(fixture(),['en','fi','sv'],GROUP,STAMP,'fi','','EN–FI','all','e'*64)
            with self.assertRaises(LookupError):cell_detail(fixture(),['en','fi','sv'],GROUP,STAMP,'fi','','all','all','f'*64)

    def test_search_requires_local_review_token(self):
        with app.test_client() as client:
            self.assertEqual(client.post('/explore/api/search',json={'query':'peace'}).status_code,403)

    def test_matrix_read_has_no_inference(self):
        with patch('paired_history.summary',return_value=fixture()),patch('heatmap.public_catalog',return_value=dict(rows=[])),patch('heatmap.query_vector',side_effect=AssertionError('GET must not embed')):
            with app.test_client() as client:self.assertEqual(client.get('/explore/api/matrix').status_code,200)

    def test_invalid_occurrence_is_rejected_before_database_read(self):
        with patch('paired_history.summary') as read:
            with app.test_client() as client:response=client.get('/explore/api/cell?run='+'a'*64+'&group='+GROUP+'&stamp='+STAMP+'&occurrence=invalid')
        self.assertEqual(response.status_code,400);read.assert_not_called()


if __name__=='__main__':unittest.main()

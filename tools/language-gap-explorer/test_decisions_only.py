import json,unittest
from unittest.mock import patch,MagicMock
from decisions_review import process_batch
from review_view import select_languages,section_groups

class FastReviewTests(unittest.TestCase):
    def test_highlight_offsets_escape_source_html(self):
        from review_view import highlight_source
        quote='<script> 1999 and 2000'
        rendered=str(highlight_source(quote,[{'start':9,'end':13}]))
        self.assertNotIn('<script>',rendered)
        self.assertIn('<mark>1999</mark>',rendered)
    def test_language_pairs_and_triplet(self):
        self.assertEqual(select_languages(['en','fi'],{'en':1,'fi':1,'sv':1},'en','fi'),['en','fi'])
        with self.assertRaises(ValueError): select_languages(['en'],{'en':1},'en','fi')
        findings=[{'id':'a','category':'conflict','evidence':[{'lang':'en','section':'History'},{'lang':'fi','section':'Historia'}]},
          {'id':'b','category':'coverage','evidence':[{'lang':'en','section':'Language'},{'lang':'sv','section':'Språk'}]}]
        for finding in findings:
            finding['title']='Example claim'
            for e in finding['evidence']: e['quote']='Example source passage.'
        chosen,groups=section_groups(findings,['en','fi']); self.assertEqual(len(chosen),1)
        chosen,groups=section_groups(findings,['en','fi','sv']); self.assertEqual(len(chosen),2)

    def verdict(self,category,probability):
        aa={'en':{'text':'The legislation was adopted in 1999.','title':'Example','rev_id':1},
          'fi':{'text':'The legislation was adopted in 2000.','title':'Example fi','rev_id':2}}
        pp=[{'id':l*32,'lang':l,'text':a['text'],'heading':'History','start_offset':0} for l,a in aa.items()]
        group={'id':'group','anchor_id':pp[0]['id'],'payload':json.dumps(pp)}
        def answer(evidence,questions):
            result={}
            for q in questions:
                if q['name'].endswith('_relation'): result[q['name']]={'choice':category,'confidence':.9}
                elif q['type']=='predicate': result[q['name']]={'probability':probability}
                else: result[q['name']]={'choice':q['choices'][1]['value']}
            return result
        con=MagicMock(); cursor=con.__enter__.return_value.cursor.return_value.__enter__.return_value
        with patch('decisions_review.decisions',side_effect=answer) as api,patch('decisions_review.connect',return_value=con):
            process_batch([group],aa)
            self.assertEqual(api.call_count,1)
        return json.loads(cursor.execute.call_args.args[1][1])[0]

    def test_highlight_only_for_qualified_conflict(self):
        f=self.verdict('conflict',.95)
        self.assertTrue(all(e['highlight']==e['quote'] for e in f['evidence']))
        for category,p in [('coverage',.95),('same',.95),('conflict',.79)]:
            f=self.verdict(category,p)
            self.assertTrue(all(not e['highlight'] for e in f['evidence']))

    def test_generation_endpoint_is_disabled(self):
        from live_api import call,APIError
        with self.assertRaises(APIError): call('responses',{},'disabled')

if __name__=='__main__': unittest.main(verbosity=2)

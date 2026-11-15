import copy
import unittest
from candidate_eligibility import assess_evidence,derive

def evidence(section='Introduction',lang='fi'):
    return [dict(lang='en',section='Introduction',quote='The treaty was concluded in 1809.',revision=1,start=0,end=32),
            dict(lang=lang,section=section,quote='Freds fördraget i Fredrikshamn / Haminan rauhansopimus 17.9.1809 Pauli Kruhse.',revision=2,start=10,end=85)]

class CandidateEligibilityTests(unittest.TestCase):
    def test_cached_external_resource_failure_pattern(self):
        result=assess_evidence(evidence('Aiheesta muualla'))
        self.assertEqual(result['status'],'reference_material')
        self.assertEqual(result['excluded_sides'],[1])

    def test_rule_uses_heading_and_language_not_quote_keywords(self):
        self.assertEqual(assess_evidence(evidence())['status'],'eligible_under_this_rule')
        self.assertEqual(assess_evidence(evidence('Aiheesta muualla sodan aikana'))['status'],'eligible_under_this_rule')
        self.assertEqual(assess_evidence(evidence('Aiheesta muualla','en'))['status'],'eligible_under_this_rule')

    def test_whitespace_case_and_missing_metadata(self):
        self.assertEqual(assess_evidence(evidence('  AIHEESTA\n MUUALLA  '))['status'],'reference_material')
        self.assertEqual(assess_evidence(evidence(None))['status'],'unknown')
        self.assertEqual(assess_evidence(None)['status'],'unknown')
        self.assertEqual(assess_evidence([{}])['status'],'unknown')

    def test_same_text_in_prose_and_reference_section_has_separate_derivations(self):
        first=dict(evidence=evidence('Aiheesta muualla'),kind='coverage',scores={'coverage':{'probability':.99}})
        second=copy.deepcopy(first);second['evidence'][1]['section']='History'
        a=derive('same-text-pair',first,'source-snapshot')
        b=derive('same-text-pair',second,'source-snapshot')
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual(a['eligibility']['status'],'reference_material')
        self.assertEqual(b['eligibility']['status'],'eligible_under_this_rule')
        self.assertEqual(a['original']['kind'],'coverage')

    def test_original_scores_and_source_offsets_are_immutable(self):
        original=dict(evidence=evidence('Aiheesta muualla'),kind='coverage',scores={'coverage':{'probability':.99}})
        before=copy.deepcopy(original);result=derive('occurrence',original,'snapshot')
        self.assertEqual(original,before)
        self.assertEqual(result['original'],before)
        result['original']['evidence'][1]['start']=999
        self.assertEqual(original,before)

    def test_article_prose_remains_eligible_but_never_claimed_validated(self):
        for lang in ('en','fi','sv','ru'):
            self.assertEqual(assess_evidence(evidence('Introduction',lang))['status'],'eligible_under_this_rule')
        self.assertIn('does not establish',assess_evidence(evidence())['reason'])

if __name__=='__main__':unittest.main()

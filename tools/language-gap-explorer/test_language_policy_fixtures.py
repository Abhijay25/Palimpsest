"""Real cached scores and controlled synthetic baseline; no new model calls."""
import json
from pathlib import Path
import unittest
from relationship_policy import classify
from issue_context_questions import request_for,exact_witnesses

FIXTURES=Path(__file__).with_name('fixtures')

class LanguagePolicyFixtureTests(unittest.TestCase):
    def test_real_conflicting_signals_abstain(self):
        cases=json.loads((FIXTURES/'language-policy-real-cases.json').read_text(encoding='utf-8'))['cases']
        karl=next(c for c in cases if c['id'].startswith('72ab7a0a'))
        self.assertEqual(karl['original_kind'],'contradiction')
        self.assertEqual(classify(karl['scores']),'uncertain')
        # Preserve the known scope-predicate limitation instead of claiming a recall gain.
        erich=next(c for c in cases if c['id'].startswith('8fba7c90'))
        self.assertEqual(classify(erich['scores']),'framing')

    def test_cached_synthetic_results_are_reproducible_and_separate(self):
        report=json.loads((FIXTURES/'synthetic-baseline.json').read_text(encoding='utf-8'))
        scores=report['scores'];truth=[False,True,False,True,True,False,False,True,False,True]*4
        tp=sum(t and p>=.8 for t,p in zip(truth,scores));fp=sum(not t and p>=.8 for t,p in zip(truth,scores))
        self.assertEqual((len(scores),tp,fp),(40,16,0))
        self.assertEqual(report['type'],'synthetic_controlled')

    def test_additional_questions_bind_exact_witnesses_and_allow_none(self):
        case=dict(evidence=[dict(lang='en',quote='The border moved west.'),dict(lang='sv',quote='Gränsen flyttades västerut.')])
        state,questions=request_for([case]);self.assertEqual(len(questions),5)
        self.assertEqual(exact_witnesses(state,0,{}),[])
        found=exact_witnesses(state,0,{'C0_E0_witness':{'choice':'S1','confidence':.99}})
        self.assertEqual(found[0]['text'],case['evidence'][0]['quote'])

if __name__=='__main__':unittest.main()

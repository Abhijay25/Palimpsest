"""Signal-consistency regressions. Constructed score fixtures are not ground truth."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from relationship_policy import classify,derive,definition,digest,classify_focused_snapshot,derive_focused_snapshot

def scores(**overrides):
    p=dict(related=1.,contradiction=0.,same_scope=1.,framing=0.,coverage=0.,compatible=1.)
    p.update(overrides)
    return {key:dict(probability=value) for key,value in p.items()}

class RelationshipPolicyTests(unittest.TestCase):
    def test_conflicting_signals_do_not_fall_through_to_framing(self):
        self.assertEqual(classify(scores(contradiction=.98,framing=.91)),'uncertain')

    def test_supported_contradiction_preserved(self):
        self.assertEqual(classify(scores(contradiction=.95,compatible=.01)),'contradiction')

    def test_framing_and_context_are_not_globally_removed(self):
        self.assertEqual(classify(scores(framing=.95,compatible=.9)),'framing')
        self.assertEqual(classify(scores(coverage=.95,compatible=.01)),'coverage')

    def test_relatedness_failure_is_not_an_omission(self):
        self.assertEqual(classify(scores(related=.3,coverage=.99)),'retrieval_failure')

    def test_scope_mismatch_is_not_contradiction(self):
        self.assertNotEqual(classify(scores(contradiction=.99,same_scope=.2,compatible=0.)),'contradiction')

    def test_refusals_and_invalid_probabilities_are_not_negative_evidence(self):
        for invalid in (None,True,False,'0.0',float('nan'),float('inf'),-.1,1.1):
            with self.subTest(invalid=invalid):
                self.assertEqual(classify(scores(compatible=invalid,contradiction=.95)),'unassessed')
        p=scores();del p['compatible']
        self.assertEqual(classify(p),'unassessed')
        self.assertEqual(classify({'related':None}),'unassessed')
        self.assertEqual(classify(None),'unassessed')

    def test_derivation_keeps_original_output_and_has_separate_identity(self):
        original=dict(kind='contradiction',scores=scores(contradiction=.98,framing=.91),question='coverage')
        before=copy.deepcopy(original)
        result=derive('original-pair',original,'snapshot')
        self.assertEqual(original,before)
        self.assertEqual(result['original'],before)
        self.assertEqual(result['kind'],'uncertain')
        self.assertEqual(result['policy_id'],digest(definition()))
        self.assertNotEqual(result['id'],'original-pair')
        self.assertEqual(result['id'],derive('original-pair',original,'snapshot')['id'])
        self.assertNotEqual(result['id'],derive('original-pair',original,'another-snapshot')['id'])
        result['original']['scores']['compatible']['probability']=0
        self.assertEqual(original,before)

    def test_cli_is_offline_and_refuses_to_replace_a_derivation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);source=folder/'source.jsonl';target=folder/'derived.jsonl'
            source.write_text(json.dumps(dict(id='pair',baseline=dict(kind='contradiction',scores=scores(contradiction=.98))))+'\n',encoding='utf-8')
            command=[sys.executable,'-B',str(Path(__file__).with_name('replay_relationship_policy.py')),'--input',str(source),'--output',str(target)]
            first=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            content=target.read_bytes()
            self.assertEqual(json.loads(content)['kind'],'uncertain')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(target.read_bytes(),content)

    def test_focused_milestone_clarification_is_not_a_strict_conflict(self):
        original=dict(engine='decisions-only-focused',category='conflict',decision=dict(
            needs_review=dict(probability=.99),same_claim=dict(probability=.01),
            relationship=dict(choice='different_milestones')))
        before=copy.deepcopy(original)
        self.assertEqual(classify_focused_snapshot(original),'uncertain')
        result=derive_focused_snapshot('finding',original,'snapshot')
        self.assertEqual(result['kind'],'uncertain')
        self.assertEqual(result['original'],before)
        self.assertEqual(original,before)

    def test_focused_different_values_still_requires_scope_and_incompatibility(self):
        value=dict(engine='decisions-only-focused',category='conflict',decision=dict(
            needs_review=dict(probability=.99),relationship=dict(choice='different_values')))
        self.assertEqual(classify_focused_snapshot(value),'uncertain')
        value['decision'].update(incompatible=dict(probability=.95),same_scope=dict(probability=.9))
        self.assertEqual(classify_focused_snapshot(value),'conflict')
        value['decision']['same_scope']['probability']=.3
        self.assertEqual(classify_focused_snapshot(value),'uncertain')

    def test_snapshot_policy_cannot_be_silently_applied_to_another_engine(self):
        with self.assertRaises(ValueError):classify_focused_snapshot(dict(engine='decisions-only',category='conflict'))

if __name__=='__main__':unittest.main()

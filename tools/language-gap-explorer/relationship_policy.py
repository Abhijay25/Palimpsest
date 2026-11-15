"""Explicit, versioned cached-score replay. No providers, database, or publication.

This research policy is not an accuracy claim and does not replace historical
labels. Fresh publication requires a separately approved assessment/derivation
identity; browsing and existing paired_verdict records remain unchanged.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

VERSION = 'relationship-signal-conflict-replay-v1'
PREDICATES = ('related','contradiction','same_scope','framing','coverage','compatible')
DEFINITION = dict(version=VERSION, related_min=.6, contradiction_min=.85,
    same_scope_min=.8, framing_min=.8, coverage_min=.8, compatible_min=.8,
    aligned_contradiction_max=.2, conflict_compatible_min=.8,
    conflict_action='uncertain; do not fall through to another issue class',
    incomplete_predicates='unassessed', coverage_scope='passage-level only',
    publication='explicit isolated derivation only; never overwrite observations')

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def definition():
    return dict(DEFINITION, implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

def probability(scores, name):
    item=scores.get(name)
    value=item.get('probability') if isinstance(item,dict) else None
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        return None
    return value if math.isfinite(value) and 0<=value<=1 else None

def classify(scores):
    """Keep independent signals independent; contradictory support abstains."""
    if not isinstance(scores,dict):return 'unassessed'
    p={name:probability(scores,name) for name in PREDICATES}
    if p['related'] is None:return 'unassessed'
    if p['related']<DEFINITION['related_min']:return 'retrieval_failure'
    if any(value is None for value in p.values()):return 'unassessed'
    if p['contradiction']>=DEFINITION['contradiction_min'] and p['compatible']>=DEFINITION['conflict_compatible_min']:
        return 'uncertain'
    if p['contradiction']>=DEFINITION['contradiction_min'] and p['same_scope']>=DEFINITION['same_scope_min']:
        return 'contradiction'
    if p['framing']>=DEFINITION['framing_min']:return 'framing'
    if p['coverage']>=DEFINITION['coverage_min']:return 'coverage'
    if p['compatible']>=DEFINITION['compatible_min'] and p['contradiction']<=DEFINITION['aligned_contradiction_max']:
        return 'aligned'
    return 'uncertain'

def derive(source_id, original, source_snapshot):
    """Append-only output payload retaining complete original scores and identity."""
    if not source_id or not source_snapshot:raise ValueError('Source identity and snapshot identity are required')
    policy=definition();policy_id=digest(policy)
    original_copy=copy.deepcopy(original)
    return dict(id=digest([policy_id,source_snapshot,source_id,original_copy]),
        source_id=source_id,source_snapshot=source_snapshot,policy_id=policy_id,
        policy=policy,kind=classify(original_copy.get('scores')),
        original=original_copy,inference_calls=0,published_history_changed=False,
        status='research-derivation-unverified',
        warning='A score conflict is insufficient evidence, not verified agreement. Context differences are passage-level; no whole-article omission is established.')

def classify_focused_snapshot(finding):
    """A clarification prompt is not a strict incompatibility assessment.

    This separate path accepts only the old focused engine's payload, so its
    fields cannot silently be interpreted as six-predicate paired scores.
    """
    if finding.get('engine')!='decisions-only-focused':
        raise ValueError('Only focused snapshot findings are supported by this policy')
    if finding.get('category')!='conflict':return finding.get('category','uncertain')
    decision=finding.get('decision',{})
    if decision.get('relationship',{}).get('choice')!='different_values':return 'uncertain'
    # needs_review and not-same-claim do not prove incompatibility or same scope.
    incompatible=probability(decision,'incompatible')
    scope=probability(decision,'same_scope')
    if incompatible is None or scope is None:return 'uncertain'
    return 'conflict' if incompatible>=.85 and scope>=.8 else 'uncertain'

def derive_focused_snapshot(source_id, original, source_snapshot):
    if not source_id or not source_snapshot:raise ValueError('Source identity and snapshot identity are required')
    policy=dict(version='focused-snapshot-strict-incompatibility-replay-v1',
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        different_milestones='uncertain',needs_review_is_not_incompatibility=True,
        incompatible_min=.85,same_scope_min=.8,missing_support='uncertain',
        publication='explicit isolated derivation only; never overwrite observations')
    policy_id=digest(policy);original_copy=copy.deepcopy(original)
    return dict(id=digest([policy_id,source_snapshot,source_id,original_copy]),
        source_id=source_id,source_snapshot=source_snapshot,policy_id=policy_id,policy=policy,
        kind=classify_focused_snapshot(original_copy),original=original_copy,
        inference_calls=0,published_history_changed=False,status='research-derivation-unverified',
        warning='A clarification candidate is not a verified contradiction. The original finding remains preserved.')

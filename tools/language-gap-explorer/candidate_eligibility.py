"""Explicit occurrence-scoped reference-section eligibility replay, not a label.

The observed Finnish external-resource heading is handled generally across
articles/revisions. Text containing a reference word is never filtered.
No application, DB, embedding model or provider is imported.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

VERSION='reference-section-eligibility-v1'
REFERENCE_HEADINGS={'fi':frozenset({'aiheesta muualla'})}

def digest(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()

def normalized_heading(value):
    if not isinstance(value,str):return None
    return re.sub(r'\s+',' ',value).strip().casefold()

def assess_evidence(evidence):
    if not isinstance(evidence,list) or len(evidence)<2:
        return dict(status='unknown',excluded_sides=[],reason='Two original source contexts are required')
    excluded=[];unknown=[]
    for index,source in enumerate(evidence):
        if not isinstance(source,dict):unknown.append(index);continue
        heading=normalized_heading(source.get('section'))
        lang=source.get('lang')
        if not isinstance(lang,str) or not heading:unknown.append(index);continue
        if heading in REFERENCE_HEADINGS.get(lang.casefold(),()):excluded.append(index)
    if excluded:
        return dict(status='reference_material',excluded_sides=excluded,
            reason='At least one selected source is in an external-resource section; it is not adequate counterpart prose evidence')
    if unknown:return dict(status='unknown',excluded_sides=[],reason='Missing source language or section metadata')
    return dict(status='eligible_under_this_rule',excluded_sides=[],
        reason='No known excluded reference section; this does not establish relevance, alignment or adequate context')

def derive(source_id,original,source_snapshot):
    if not source_id or not source_snapshot:raise ValueError('Source identity and snapshot are required')
    preserved=copy.deepcopy(original)
    policy=dict(version=VERSION,scope='exact source occurrence/context; never a global text-pair relabel',
        reference_headings={k:sorted(v) for k,v in REFERENCE_HEADINGS.items()},
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        publication='research-only explicit derivation; original labels/scores/history retained')
    policy_id=digest(policy)
    return dict(id=digest([policy_id,source_snapshot,source_id,preserved]),source_id=source_id,
        source_snapshot=source_snapshot,policy_id=policy_id,policy=policy,
        eligibility=assess_evidence(preserved.get('evidence')),original=preserved,
        inference_calls=0,published_history_changed=False,
        warning='Reference-section exclusion is an evidence eligibility rule, not verified agreement or article-wide absence.')

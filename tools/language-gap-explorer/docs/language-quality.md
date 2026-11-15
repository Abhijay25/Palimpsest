# Language evidence quality and readable issue context

Native and preview language evidence now show one logical explanation anchored to both original passages. Context descriptions identify the source statements and classification limits; optional prepared descriptions are bound to exact language, quote, section, revision and offset identities. They do not change the stored classification or assert which edition is correct.

English machine translation belongs directly below each foreign-language paragraph in the diff. A click starts the local Argos/CTranslate2 translator; subsequent readers reuse its model/text cache. No provider call, model download, translation or preparation starts on ordinary reads. Translation requests are bound to the exact observation and original paragraph, not arbitrary caller-supplied text. Native requests require POST/CSRF and read access; preview requests require its review token. Translation text is excluded from source anchoring, so it cannot be mistaken for original evidence. Originals remain visible, unchanged and attributable.

`issue_context_questions.py` prepares additional batched Decisions questions for explicit future assessments: exact source witnesses, relationship type, context adequacy and scope. Its alternatives include compatible, different scope, retrieval miss and insufficient evidence. This follows the detector flags' evidence-basis pattern without forcing a prose explanation or counterpart witness. The builder never runs a paid request, and no new paid assessment was run for this change. Additional provider work needs its own bounded authorization.

`examples/issue-explanations/` contains a source-bound assistant-prepared description of the real pre-war territorial-demands example. To enable it, copy the JSON into `NEOWIKI_RESEARCH_ROOT/data/issue-explanations/`. This is derived presentation metadata, not a bilingual expert verdict. The generic fallback still quotes the actual source statements and explains the review criterion. Code deployment alone does not transfer this metadata, translation database rows, archived source files or local translator models; migrate the existing persistent research data/model mounts separately.

## Conservative policy replay

Future explicit passage extraction now excludes that exact normalized Finnish external-resource heading. Prose mentioning the words, longer headings, and other source languages stay eligible. Passage-cache identities and new preparation configurations include the revised extraction policy; existing revision indexes, runs and observations remain available by their original identities. Historical phase reuse also requires a matching extraction policy. No extraction, embedding or reassessment runs on browsing, and this change does not automatically reprocess the corpus. The new policy and translation regressions run in CI.

The explicit offline `replay_relationship_policy.py` command creates new derivation identities and preserves complete originals. It provides the contradiction/compatibility conflict gate, a separate focused-snapshot clarification gate and occurrence-scoped exclusion of the missed Finnish reference heading `Aiheesta muualla`. These research policies do not silently relabel published history or change existing paid-worker caches.

Measured cached baseline: 29,677 pairs; 2,061 coverage, 347 framing, one contradiction, 121 aligned, 391 uncertain, 1,635 unassessed and 25,121 retrieval failures. The narrow conflict policy changes the sole contradictory-signal pair to uncertain while preserving all framing/context counts. A broader evaluated gate would also abstain on 66 framing candidates; that coverage loss is unverified and is not enabled. The reference-section rule affects nine distinct pair IDs repeated across 161 historical occurrences, not 161 independently verified errors.

The current local latest-assessed Winter War index was checked on 2026-11-15: **135 language findings plus three detector flags**. The older 1,275 Winter War language-group identities span three historical cohorts. Display deduplication or choosing the latest set is not classification accuracy.

The offline evidence study prepared 120 revision-pinned cases across 28 topics, including 26 topic-separated held-out cases. Human/bilingual-verified labels remain unavailable. Per-class primary precision/recall and held-out gains therefore remain unknown. The committed real fixtures reproduce the Karl conflicting-signal failure and preserve the Erich minority/majority scope limitation honestly. The separate cached 40-case synthetic single-predicate English baseline has 16/20 positive recall and 0/20 false conflicts at .8; it is not validation of the multilingual six-predicate classifier. Synthetic score fixtures test safeguards, not real-world recall.

```sh
python -B -m unittest test_issue_context test_language_policy_fixtures test_relationship_policy test_candidate_eligibility test_native_issues test_issues test_flags_tab test_article_page test_evidence_highlights test_decisions_only
node test_issue_translations.js
python ../../scripts/sync_issues_assets.py --check
python -B replay_relationship_policy.py --input cases.jsonl --output new-derivations.jsonl
```

Remaining evaluation: independent bilingual/claim-level annotations, genuine positive controls, held-out class precision/recall and useful findings lost at comparable coverage. Smaller counts alone do not demonstrate improvement.

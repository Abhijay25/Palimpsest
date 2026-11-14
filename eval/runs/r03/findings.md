# r03 findings — prompt stage2_v2 on the r02 cases (45)

## Results (r02 → r03)
- Clean-flag rate: 5% → **0%** for both models. The false positive `fi_synth2_16` is fixed by the edit-relative scope rule.
- Recall: 100% → 100%.
- Exact category: 42/45 for both models. Haiku and Sonnet agreed on every verdict. `en_synth2_04` and `en_synth2_05` (hedge dropped) moved to the correct G2.
- Cost: 4 subagents instead of 10, for ~250k subagent tokens instead of ~500k.

## Remaining mismatches
- `fi_synth2_03` ("deaths of unestablished cause" → "murders") and `fi_synth2_04` (conditional leave to appeal stated as certain): both models say G1. The murder case is a genuine boundary, because calling a death a murder is arguably a new factual claim. Either way the edit is flagged, so an admin still sees it.
- **`en_spec_05` regressed** from EXPAND_CONTEXT to G1. The window says the estimate was revised but never gives a figure. NEW changes 2,900 to 4,200, so the source is *silent* on the new number: it neither supports nor contradicts it. v2's G3-vs-EXPAND rule taught the models that "coherent window" means "flag".

## Open policy question (for the user)
The rubric doesn't separate a source that *explicitly addresses and does not support* a claim (flag) from a source that is *silent* on it (abstain and fetch more). The spec's G1 treats a number change that keeps the same `<ref>` as citation hijacking (flag), while spec Case 5 expects abstention. Proposed rule for v3: silent source → EXPAND_CONTEXT → Stage 2 escalation with a wider window → flag G1/G3 if still silent. That is safer, but on real edits it may push the escalation rate far above the spec's <10%. Needs real-edit data to decide.

## Status
The synthetic sets are saturated: both models are near-perfect, so further prompt tuning on them would overfit. The next informative run is the 34 real-edit cases, which needs `EXA_API_KEY`.

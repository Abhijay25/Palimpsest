# r01 findings — fixed-source cases only (32 cases: en_spec 5, en_synthetic 15, fi_synthetic 12)

Prompt: stage2_v1. Judges: Haiku + Sonnet via Claude Code subagents. Exa key absent, so the 34 real-edit cases (en/fi reverts + controls) were NOT run.

## Results
- Both models: 31/32 matching the expected label, every flag in the right category, 0/7 clean controls flagged, 0 parse errors. Haiku and Sonnet agree on 32/32 verdicts; Sonnet's confidence is higher (0.90–0.98 vs Haiku's 0.80–0.97).
- Only miss: `en_spec_05` (spec §11 Case 5, the EXPAND_CONTEXT test). Both models output FLAG_G1_FACT. Their reasoning is defensible: the 2-sentence snippet says the figure was retracted, which is enough to flag the edit for dropping that caveat. **The test case is weak, not the model:** the snippet doesn't actually lack the information the judge needs. A real abstention test needs a snippet where the deciding fact is missing, e.g. "He denied this." with no antecedent.
- Stage 0 exits: 0/32. `en_spec_01` ("maintainence" → "maintenance", a typo fix) went to the judge because the Levenshtein ≤2 rule is too strict: the distance there is 3. The judge then cleared it correctly, but it cost a model call.

## Why these numbers overstate real-world accuracy
1. **The synthetic source window is the original paragraph itself**, so the judge can diff NEW against a source that contains OLD verbatim. Real `<ref>` sources paraphrase, and that is where errors will come from.
2. **The cases were authored by the same model family that judges them**, so their idea of a "subtle" edit may sit close to what the judges look for.
3. **There are 7 clean controls**, which is far too few to measure a 5% false-positive bar: one flag moves the rate by 14 points.
4. The real-edit buckets (Wikipedia reverts and surviving edits, EN + FI) will be the actual test.

## Changes for r02
- Run the 34 real-edit cases once `EXA_API_KEY` is set.
- Stage 0: allow typo fixes up to a relative edit distance (e.g. ≤ 0.25 of the word length) when nothing in the watch-lists, numbers or negations changes.
- Harder synthetic set: a source window written as a paraphrase in different wording from OLD; clean edits that add a detail supported by the source but not present in OLD; and more clean controls (target ≥ 20).
- Replace `en_spec_05` with a true missing-antecedent snippet.

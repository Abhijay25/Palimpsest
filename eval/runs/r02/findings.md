# r02 findings — harder fixed-source cases (45: en_spec 5, en_synthetic_v2 24, fi_synthetic_v2 16)

Prompt stage2_v1. Stage 0 change since r01: relative typo tolerance. Exa key still absent, so the real-edit cases were not run.

## Results
- Stage 0 cleared the typo case (`en_spec_01`) with no model call.
- Recall 100% for both models: every one of 25 planted violations was flagged.
- Clean-flag rate 5% for both models: 1 of 20 clean cases flagged, `fi_synth2_16`.
- Spec Case 5 (rebuilt with a genuinely insufficient snippet): both models now answer EXPAND_CONTEXT.
- Haiku and Sonnet disagreed on the category in 2 cases. Every one of the 6 mismatches against the expected label is a category confusion or a judgement call, never a missed violation.

## Mismatches and causes
| Case | Expected | Haiku / Sonnet | Cause |
|---|---|---|---|
| en_synth2_04, fi_synth2_03, fi_synth2_04 | G2 (hedge dropped) | split, or both G1 | **The spec's rubric overlaps here.** G1 includes "strip a mandatory caveat" while G2 includes "distorts epistemic certainty", so dropping a hedge fits both. |
| en_synth2_05 | G2 | Haiku G3 / Sonnet G2 | Same boundary: "proves a deliberate…" reads as both overstated certainty and an implied intent. |
| en_synth2_11 | EXPAND_CONTEXT | both G3 | **The label was wrong.** "He" refers to the spokesperson in the window, and the window explicitly says he declined to give a reason, so the window is sufficient and the added cause is unsupported. Relabelled to G3 for r03, recorded in the case notes. |
| fi_synth2_16 | CLEAN_PASS | both G1 | **A real false positive.** The edit *improved* attribution ("thus" → "according to scholars"), but the judges flagged it because the source says "most scholars". The rubric scores NEW against the source without asking whether the edit made things worse than OLD. For editor trust scores this matters: editors would be penalised for improvements and for text they never touched. |

## Changes for r03 (prompt stage2_v2 = v1 + scope and tie-break rules)
1. Edit-relative scope: flag only problems the edit introduced or worsened compared with OLD.
2. G1 only when *what* is claimed changes (truth value, number, entity, quantifier). Certainty, hedge, attribution and verb changes on the same fact are G2.
3. G3 when a coherent window doesn't state the motive. EXPAND_CONTEXT only when the window is broken (unresolved referent, truncation).

## Cost note
Each judge subagent used ~40–65k tokens, mostly fixed Claude Code overhead, not the cases themselves. r03 uses batches of 25 instead of 10 (2 subagents per model instead of 5).

## Caveat (applies to every run)
The judges run as Claude Code subagents with their own system prompt, not as bare API calls, so these results indicate verdict quality rather than reproduce an API backend. Stage 2 latency is not measured.

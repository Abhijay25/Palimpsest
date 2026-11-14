# r14screen — short first-pass screen prompt (Haiku), 2026-11-14 15:40

Goal (efficiency/resources): a first pass that outputs only verdict + confidence (empty arrays) with a condensed rubric, so the ~80% of edits that pass cost fewer tokens and return faster; flags go to the full judge (cascade).

`screen_v1.txt`: 2.3k chars vs 7.6k for stage2_v7; output ~190 chars/case vs ~770 (measured on result files). Same rules as v7, condensed; no eval examples.

140 real edits (34 reverts, 106 controls) with full Sonnet verdicts from r08en/r11fi/r12v7ctl as the second stage:

| First pass (escalate on flag) | reverts reaching admin (of Sonnet-alone 16) | clean edits escalated to Sonnet | clean edits reaching admin |
|---|---|---|---|
| Haiku + screen_v1 | 14 | 27% | 5 (= Sonnet alone) |
| Haiku + full prompt | 13 | 14% | 5 (= Sonnet alone) |

Counting EXPAND as escalation too: screen 39% vs full 19% of clean edits.

Read: the screen keeps recall (14 vs 13) and precision (identical admin set) and cuts first-pass tokens ~3x in / ~4x out, but escalates twice as many clean edits. With Sonnet ≈3x Haiku per token the total is roughly a wash; latency on pass-through edits is better with the screen. **Decision: keep the full prompt as the first pass for now; re-evaluate the screen when Gemini first-pass/Hydrogen prices and latencies are known [review].**

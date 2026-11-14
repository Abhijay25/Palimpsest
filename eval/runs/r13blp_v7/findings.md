# r12v7ctl + r13blp — stage2_v7 (WP:BLP exception to the silent-source rule), 2026-11-14 15:25

**Change:** v6's silent-source rule passed any added claim the source does not mention. v7 adds one bullet: an added claim that would damage an identifiable person's or organisation's reputation (wrongdoing, crime, arrest, investigation, lawsuit, misconduct, health, sexuality, extremist ties, insolvency) needs explicit support, else `FLAG_G1_FACT` (citation hijacking). Grounded in WP:BLP / WP:V; no eval example in the prompt. Motivated by blind r11fi (a KGB allegation passed).

## r13blp — blind synthetic set (24: 12 contentious / 12 neutral unsourced additions, en 16 / fi 8, fixed windows)
| | contentious flagged | neutral flagged |
|---|---|---|
| v6 Haiku | 1/12 | 0/12 |
| v6 Sonnet | 1/12 | 0/12 |
| v7 Haiku | **12/12** (all admin) | **0/12** |
| v7 Sonnet | **12/12** (all admin) | **0/12** |
Caveat: the writer's category list and the prompt's both come from WP:BLP, so this set mostly confirms the rule is applied and does not spill onto neutral additions.

## r12v7ctl — false-alarm check on 106 real controls (en 76, blind fi 30; 6 stage-0 clean)
| | v6 admin (≥0.70) | v7 admin |
|---|---|---|
| Sonnet en (71 judged) | 2 | 4 |
| Sonnet fi (29) | 0 | 1 |
| Haiku en (71) | 4 | 8 |
| Haiku fi (29) | 2 | 2 |
New admin flags caused by the rule: 1 Sonnet, 1 Haiku — and **both are real BLP problems patrol missed**: an edit saying a former president was "convicted" when the cited article says "charged"; an edit adding that a named man behaved violently, absent from the cited 2007 article. The rest of the change is run-to-run confidence variance (cases crossing 0.70 both ways), which is large: single-run admin counts on 71 controls move by ±2 with no prompt change. **[review]** decisions on these numbers need repeated runs or Gemini's lower-variance decoding.

Also found: 9/100 Haiku CLEAN_PASS outputs omitted `flagged_spans`/`neutral_rewrite`; these are now filled at parse time for non-flag verdicts only (commit "Fill empty-by-definition fields").

Decision: **stage2_v7 is the default.** Haiku's admin-queue false-alarm rate on English controls (8/71 = 11%) is above the bar; Haiku stays a first pass, not the admin gate.

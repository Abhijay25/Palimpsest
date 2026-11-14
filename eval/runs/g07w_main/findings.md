# g07w: weighted-aggregation v9 (variant B), live, 2026-11-15

Same code and sets as g08 (eval/runs/reviewer/live_findings.md). 124 Hydrogen calls (422k in / 72k out / 62k thinking).

| group (admin/review/n) | g08_base (v8) | g07w (weighted v9) |
|---|---|---|
| clean controls en / fi | 1/0, 2/0 of 30 | 1/0, 1/0 of 30 |
| BLP synthetic | 12/0/24 | 12/0/24 |
| FACTUAL_ERROR | 2/0/5 | 1/0/5 |
| POV_FRAMING | 5/0/6 | 1/0/6 |
| UNSOURCED_CONTENTIOUS | 4/0/6 | 3/1/6 |
| REMOVED_SOURCED_CONTENT | 1/0/2 | 0/0/2 |
| VANDALISM | 7/0/8 | 1/0/8 |
| scout real swaps (25) | 7/7 | 0/0 |
| scout controls (25) | 0/0 | 0/0 |
| owner labels (case level) | all 10 cases admin | all 10 cases none: 3 "n" removed, 7 "y" lost |

Over-corrects: the weights suppress real problems with the noise. The six scenarios do not cover non-encyclopedic content (vandalism, first-person appeals, opinions) — the owner's highest-priority "y" class — so those fall to WEAK free-form notes; single-signal POV wording falls below the review threshold. Not adopted.

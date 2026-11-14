# Argon reviewer (variant A), live, 2026-11-15

Runs on the same code (stage2_v8, Exa highlights, value check on, value-swap review rule off): g08_base (no reviewer) vs g08_rev (reviewer, gemini-4-argon LOW), 125-case set; g08_scout_base vs g08_scout_rev, 50 real Finnish scout cases.

| group (admin/review/n) | base | + reviewer |
|---|---|---|
| clean controls en | 1/0/30 | 2/3/30 |
| clean controls fi | 2/0/30 | 2/3/30 |
| BLP synthetic (12 should flag) | 12/0/24 | 12/7/24 |
| FACTUAL_ERROR (should) | 2/0/5 | 1/1/5 |
| POV_FRAMING (should) | 5/0/6 | 5/0/6 |
| UNSOURCED_CONTENTIOUS (should) | 4/0/6 | 4/1/6 |
| REMOVED_SOURCED_CONTENT (should) | 1/0/2 | 0/1/2 |
| VANDALISM (should) | 7/0/8 | 7/0/8 |
| no-flag-needed reverts (14) | 0/0 | 0/6 |
| scout real value swaps (25) | 7/7 | 10/8 |
| scout controls (25) | 0/0 | 0/0 |

Owner-labelled cases (eval/labels/wording_motive_user_labels.json, case level): the reviewer kept all 3 "n" cases at admin and demoted the "yy" Sparta case (removed qualifier) to review — wrong direction on the labels.

Cost: 85 Argon calls on 124 cases (122k input / 17k output tokens); 10 on the scout set.

Verdict: helps recall on real value swaps (+4 caught, 0 control noise) but on the main set its "raise borderline to review" adds 6 review flags on clean controls, 7 on neutral BLP additions and 6 on no-flag reverts, and it does not demote the over-sensitive wording flags. Not adopted as is. If kept: drop raise_to_review except for value changes, and make demotion of wording flags follow docs/flag-policy.md explicitly.

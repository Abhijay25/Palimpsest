# g05: Exa highlights (v8) and the guided judge v9, Hydrogen LOW, same 125 cases as g03/g04

Runs: g05_v8_hl (stage2_v8 + highlights + value-swap review rule), g05_v9_hl (stage2_v9 guided + highlights). Baseline g04_v8_low (v8, lexical windows, no value-swap rule). Tiers: admin >= 0.70, review 0.45-0.70.

| group (admin/review/n) | g04 v8 lexical | g05 v8 highlights | g05 v9 highlights |
|---|---|---|---|
| clean controls en | 1/0/30 | 1/0/30 | 2/13/30 |
| clean controls fi | 1/0/30 | 2/1/30 | 1/8/30 |
| BLP synthetic (12 should flag) | 12/0/24 | 12/0/24 | 12/12/24 |
| FACTUAL_ERROR (should) | 1/0/5 | 1/2/5 | 1/3/5 |
| POV_FRAMING (should) | 5/0/6 | 5/0/6 | 5/1/6 |
| UNSOURCED_CONTENTIOUS (should) | 4/0/6 | 4/0/6 | 4/1/6 |
| REMOVED_SOURCED_CONTENT (should) | 1/0/2 | 1/0/2 | 0/1/2 |
| VANDALISM (should) | 7/0/8 | 7/0/8 | 4/3/8 |
| no-flag-needed reverts (14) | 0/0 | 0/1 | 0/7 |

Highlights: usable source passage 57 -> 64 cases; 219 Exa calls ($0.17) for the v9 run, 53 for v8 (cache). The two extra factual-error catches in v8_hl come from the value-swap rule (review tier).

v9 as built is worse: 21/60 clean edits and 12/12 neutral BLP additions get a review flag. Cause (from its own reasons): S1 sends a changed value to review even when it says the source supports the NEW value ("2024-25 -> 2025-26, which is supported by the source. Is this a concern?"), and the free-form concern slot turns any unsupported detail into a review flag. Fix before re-measuring: S1 flags only when the source supports the OLD value (admin) and drops when it supports the new one; free-form concerns need a contradicting source quote. Default stays stage2_v8.

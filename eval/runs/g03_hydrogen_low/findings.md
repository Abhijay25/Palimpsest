# g03: Hydrogen LOW vs HIGH thinking at scale (stage2_v7)

125 cases (124 judged): blind English set (en_reverts3 21 + en_controls3 30, never judged before), blind Finnish set (r11fi: 20 reverts + 30 controls), BLP synthetic (24). Runs g03_hydrogen_low and g03_hydrogen_high. Per-call timing, concurrency 4.

| | LOW | HIGH |
|---|---|---|
| flag/no-flag agreement | 124/124 identical | |
| English reverts flagged | 9/21 (POV-summary reverts 7/10, other 2/11) | same |
| English clean edits flagged | 1/30 | 1/30 |
| Finnish reverts flagged | 8/20 | 8/20 |
| Finnish clean edits flagged | 1/30 | 1/30 |
| BLP synthetic exact | 24/24 | 24/24 |
| EXPAND_CONTEXT verdicts | 2 | 5 |
| latency p50 / p90 / p95 / max | 4.4 / 6.4 / 7.1 / 11.3 s | 6.5 / 14.0 / 17.1 / 33.1 s |
| tokens per call (in / out / thinking) | 3.2k / 242 / 514 | 3.2k / 250 / 1,234 |

Decision: LOW is the default. HIGH changed no flag decision on 124 edits while costing 2.4x the thinking tokens and 2.4x the p95 latency; it only turns a few verdicts into EXPAND_CONTEXT.

Compared with the Claude stand-ins on the same Finnish set (r11fi): Sonnet flagged 11/20 reverts and 0/30 controls, Haiku 9/20 and 5/30. Hydrogen is at Sonnet's precision with slightly lower recall. False-alarm rate on clean edits is 2/60 (3%) across both languages, against Haiku's 11% on English controls.

Recall on reverts that were not reverted for POV/sourcing reasons is low (2/11) by design: those reverts are mostly for reasons a source comparison cannot see.

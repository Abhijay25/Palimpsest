# g02: Hydrogen vs Argon at different thinking levels (stage2_v7)

Same 15 cases (14 judged): spec 1-5, 3 Finnish reverts, 3 Finnish controls, 4 BLP synthetic (2 contentious, 2 neutral). Labels: spec/BLP from case files; real cases as in g01 findings; fi_revert_22022025 unlabelled. Runs: g02_hydrogen_low, g02_hydrogen_high, g02_argon_low, g02_argon_medium. Timing is per call (inside the semaphore, d5734f2), concurrency 4.

| config | correct | p50 | max | thinking tokens / call |
|---|---|---|---|---|
| hydrogen LOW | 13/14 (spec 5 -> G1) | 4.9 s | 8.9 s | ~545 |
| hydrogen HIGH | **14/14** | 7.7 s | 28.3 s (spec 5) | ~1,310 |
| argon LOW | 13/14 (unsourced violence claim -> EXPAND) | 9.0 s | 13.4 s | 0 |
| argon MEDIUM | 13/14 (same) | 10.3 s | 22.2 s | ~63 |

Input ~3.1k tokens and output ~330 tokens per call in every config.

- Argon is slower than Hydrogen at every level tried and no more accurate: dropped.
- Hydrogen HIGH is the only config with no error; its slowest call is the hardest case (spec 5, EXPAND guardrail).
- Hydrogen LOW and HIGH agree on every CLEAN verdict; they differ only on one flag. A LOW -> HIGH cascade (re-judge only flags) would have scored 14/14 here.
- Confidence stays saturated in every config (flags 0.85-1.00, cleans 0.50-0.90): routing cannot rely on the 0.70 threshold.
- Sample is 14 cases: a direction, not a measurement.

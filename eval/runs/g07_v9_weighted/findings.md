# g07: stage2_v9 weighted aggregation, Hydrogen LOW

Tiers: admin >= 0.70, review 0.45-0.70. `g07` prepared both requested runs, but restricted outbound networking stopped Gemini generation before `results/` was written, so no new counts are inferred.

| group (admin/review/n) | g05 v8 highlights | g05 old v9 highlights | g07 weighted v9 |
|---|---|---|---|
| clean controls en | 1/0/30 | 2/13/30 | unavailable/30 |
| clean controls fi | 2/1/30 | 1/8/30 | unavailable/30 |
| BLP synthetic (12 should flag) | 12/0/24 | 12/12/24 | unavailable/24 |
| FACTUAL_ERROR (should) | 1/2/5 | 1/3/5 | unavailable/5 |
| POV_FRAMING (should) | 5/0/6 | 5/1/6 | unavailable/6 |
| UNSOURCED_CONTENTIOUS (should) | 4/0/6 | 4/1/6 | unavailable/6 |
| REMOVED_SOURCED_CONTENT (should) | 1/0/2 | 0/1/2 | unavailable/2 |
| VANDALISM (should) | 7/0/8 | 4/3/8 | unavailable/8 |
| no-flag-needed reverts (14) | 0/1/14 | 0/7/14 | unavailable/14 |

| group (admin/review/n) | g06 v8 highlights | g06 old v9 highlights | g07 weighted v9 |
|---|---|---|---|
| fi scout swaps | 11/8/25 | 1/20/25 | unavailable/25 |
| fi scout controls | 0/9/25 | 0/17/25 | unavailable/25 |

The owner-labelled Wording/Motive items are development data, not a held-out metric. New weighted-v9 admin precision is unavailable without Gemini output; the prior policy baseline is 12/22 (55%, excluding unsure/duplicates).

```sh
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --cases eval/cases/en_reverts3.jsonl eval/cases/en_controls3.jsonl eval/cases/fi_blind_reverts.jsonl eval/cases/fi_blind_controls.jsonl eval/cases/blp_silence.jsonl --run eval/runs/g07_v9_weighted/main --models gemini-4-hydrogen --prompt stage2_v9 --source-mode highlights --backend gemini
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --cases eval/cases/fi_scout_swaps.jsonl eval/cases/fi_scout_controls.jsonl --run eval/runs/g07_v9_weighted/scout --models gemini-4-hydrogen --prompt stage2_v9 --source-mode highlights --backend gemini
```

# Reviewer evaluation

Live measurement was not completed in this sandbox. `prepare` wrote the 125 prepared
cases, then the outbound Gemini generation phase was stopped by the restricted sandbox
before it produced `results/`; no reviewer or baseline result rows exist.  Counts, latency,
and token figures below are therefore deliberately not inferred.

| group | Hydrogen admin/review | reviewer admin/review | reviewer calls | added p50/p95 | tokens |
|---|---:|---:|---:|---:|---:|
| clean controls en | unavailable | unavailable | unavailable | unavailable | unavailable |
| clean controls fi | unavailable | unavailable | unavailable | unavailable | unavailable |
| BLP synthetic | unavailable | unavailable | unavailable | unavailable | unavailable |
| FACTUAL_ERROR | unavailable | unavailable | unavailable | unavailable | unavailable |
| POV_FRAMING | unavailable | unavailable | unavailable | unavailable | unavailable |
| UNSOURCED_CONTENTIOUS | unavailable | unavailable | unavailable | unavailable | unavailable |
| REMOVED_SOURCED_CONTENT | unavailable | unavailable | unavailable | unavailable | unavailable |
| VANDALISM | unavailable | unavailable | unavailable | unavailable | unavailable |
| no-flag-needed reverts | unavailable | unavailable | unavailable | unavailable | unavailable |
| fi scout swaps | unavailable | unavailable | unavailable | unavailable | unavailable |
| fi scout controls | unavailable | unavailable | unavailable | unavailable | unavailable |

The labelled Wording/Motive development set starts at 12/22 admin-tier precision (55%,
excluding unsure/duplicates) per `docs/flag-policy.md`; after-review precision is unavailable
until the live reviewer run completes.  The 125-case and scout sets remain the held-out check.

Run from the repository root (the command creates `reviewer.jsonl` with per-edit calls,
latency, and tokens):

```sh
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --cases eval/cases/en_reverts3.jsonl eval/cases/en_controls3.jsonl eval/cases/fi_blind_reverts.jsonl eval/cases/fi_blind_controls.jsonl eval/cases/blp_silence.jsonl --run eval/runs/reviewer/baseline --models gemini-4-hydrogen --prompt stage2_v8 --source-mode highlights --backend gemini
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --cases eval/cases/en_reverts3.jsonl eval/cases/en_controls3.jsonl eval/cases/fi_blind_reverts.jsonl eval/cases/fi_blind_controls.jsonl eval/cases/blp_silence.jsonl --run eval/runs/reviewer/with_reviewer --models gemini-4-hydrogen --prompt stage2_v8 --source-mode highlights --backend gemini --reviewer
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --cases eval/cases/fi_scout_swaps.jsonl eval/cases/fi_scout_controls.jsonl --run eval/runs/reviewer/scout --models gemini-4-hydrogen --prompt stage2_v8 --source-mode highlights --backend gemini --reviewer
```

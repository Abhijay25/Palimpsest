# Context-read modes

Run date: 2026-11-15. The live evaluation was not run: this sandbox cannot resolve
`api.exa.ai` (`curl --silent --show-error --connect-timeout 3 --max-time 5 -o /dev/null
-w '%{http_code}\n' https://api.exa.ai/contents` returned `curl: (6) Could not resolve
host: api.exa.ai`, `000`). Gemini results would not be meaningful without the added Exa
context, so no synthetic substitutions were made.

| mode | labelled y/n precision | `?` outcomes | catches / clean flags | extra Exa calls | added p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| never | not measured | not measured | not measured | not measured | not measured |
| rule | not measured | not measured | not measured | not measured | not measured |
| always | not measured | not measured | not measured | not measured | not measured |

When DNS is available, run each command once with `MODE=never`, `MODE=rule`, and
`MODE=always` (the manifests retain per-run Exa and Gemini timing data):

```sh
MODE=rule; UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --backend gemini --reviewer --followup --context-mode "$MODE" --run "eval/runs/context/g05_$MODE" --cases eval/cases/en_reverts3.jsonl eval/cases/en_controls3.jsonl eval/cases/fi_blind_reverts.jsonl eval/cases/fi_blind_controls.jsonl eval/cases/blp_silence.jsonl
MODE=rule; UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --backend gemini --reviewer --followup --context-mode "$MODE" --run "eval/runs/context/fi_scout_$MODE" --cases eval/cases/fi_scout_swaps.jsonl eval/cases/fi_scout_controls.jsonl
MODE=rule; UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest prepare --backend gemini --reviewer --followup --context-mode "$MODE" --run "eval/runs/context/owner_$MODE" --cases eval/cases/en_reverts3.jsonl eval/cases/en_controls3.jsonl eval/cases/fi_blind_reverts.jsonl eval/cases/fi_blind_controls.jsonl
```

The third input set contains the case IDs referenced by the 26 owner labels; score its
flags against `eval/labels/wording_motive_user_labels.json`, preserving all three `?`
items as outcomes rather than precision labels. Recommended default: `rule`, because it
only consults the whole source for absence and removed-context claims, while keeping the
six-call/six-second request bound. Reconfirm this recommendation after the live table is
populated.

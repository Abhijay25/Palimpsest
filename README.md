# Palimpsest
HackJunction 2026 Project

## Switching to Gemini

The default judge backend is the Claude-subagent file exchange. To judge through
the Gemini API instead, set the key in `.env` (never commit it) and pass one flag:

```
GEMINI_API_KEY=...            # required
PALIMPSEST_USE_GEMINI=1       # required opt-in; without it the key is never used
GEMINI_FIRST_PASS_MODEL=...   # optional: cheap first pass; only its flags go to GEMINI_JUDGE_MODEL
GEMINI_JUDGE_MODEL=gemini-4-hydrogen    # optional
GEMINI_TRIAGE_MODEL=gemini-decision-1   # optional (GeminiTriageBackend)
GEMINI_CONCURRENCY=8          # optional, parallel calls
GEMINI_TIMEOUT_SECONDS=60     # optional, per call
GEMINI_THINKING_LEVEL=LOW     # optional: MINIMAL|LOW|MEDIUM|HIGH|XHIGH (judge default LOW, see eval/runs/g03_hydrogen_low)

nix develop -c uv run python -m palimpsest prepare --cases c.jsonl --run runs/g1 --backend gemini
nix develop -c uv run python -m palimpsest ingest --run runs/g1
```

`prepare --backend gemini` runs Stage 0/1, calls the API inline (one retry on
429/5xx), records `stage2_ms` per case, and writes results so `ingest` and the
report work unchanged. `--models` is ignored; the model name comes from
`GEMINI_JUDGE_MODEL`. A missing key exits non-zero before any network call.

## API

```
nix develop -c uv run uvicorn palimpsest.api:app --port 8000
```

`GET /healthz` returns booleans only: `{"judge_configured": bool, "exa_configured": bool}`.
`lang_code` is any Wikipedia language code (`en`, `fi`, `de`, `zh-yue`, ...); en/fi
also get Stage 0 watch-list reasons, other languages only the language-neutral rules.
`audit-diff` returns 503 when no judge is enabled (`GEMINI_API_KEY` and
`PALIMPSEST_USE_GEMINI=1`) and Stage 0 is not clean (no verdict is faked), 502 if a
judge call fails.

For one edit, `python -m palimpsest diagnose --case cases.jsonl [--case-id ID] [--json]`
runs the exact in-process `audit-diff` pipeline and prints its stages, latencies, and
verdict details; alternatively supply `--old`, `--new`, `--lang`, `--title`, and
repeatable `--ref`. If Stage 0 is not clean and no judge is configured, it prints the
completed stages without inventing a verdict and exits 3.

`POST /api/v1/cross-lingual` is an explicit cold-path endpoint. It accepts
`lang_code`, `page_title`, `claim_text`, and `edit_verdict`, then returns local-citation
audits for linked target wikis plus a divergence warning. It is never called by
`audit-diff`; configure `PALIMPSEST_CROSSLINGUAL_LANGS` as a comma-separated target list
to override its default `en,fi,de,fr,es` set.

The edit is split into changed paragraphs (`units`), judged 4 at a time; more than 12
changed paragraphs are capped (`partial: true`, route at least `review`). The top-level
verdict is the most severe unit. `reason` / `reason_text` describe a flag
(`CONTRADICTS_SOURCE`, `UNSUPPORTED_CLAIM`, `LOADED_WORDING`, `REMOVED_CONTEXT`)
without inferring intent. `render` reports the concurrent headless-browser scan of
cited pages the edit touched (Pillar 3); it can only escalate to `admin`, never block
or delay the verdict, and is skipped for Stage-0-clean edits. Set `PALIMPSEST_RENDER=0`
to disable it; it needs a system `chromium` (or `CHROMIUM_PATH`). `editor_trust_delta` is a placeholder rule (FLAG_G1 -0.10, G2 -0.05,
G3 -0.08, stealth admin flag -0.20, else 0). Flagged-span offsets index into the
request `new_text` (null if the substring is not found).

```
curl -s localhost:8000/api/v1/stealth-scan -H 'content-type: application/json' \
  -d '{"text": "Some wikitext", "target_type": "WIKIPEDIA_DIFF", "old_text": "Old wikitext"}'

curl -s localhost:8000/api/v1/audit-diff -H 'content-type: application/json' -d '{
  "lang_code": "en", "page_title": "Example", "section_title": "History",
  "old_revision_id": 1, "new_revision_id": 2, "editor_username": "Alice",
  "old_text": "The mayor signed the bill.",
  "new_text": "The mayor shamelessly pushed through the disastrous bill.",
  "ref_urls": ["https://example.org/article"]
}'
```

## Live-page audit

`python -m palimpsest audit-page --lang sv --title Tornedalingar --max-paragraphs 12 --json report.json`
audits the current revision. It always scans the whole wikitext for stealth content
and checks rendered dates using month names supplied by that wiki's interface messages.
It also compares dates beside historical Wikipedia revision links. Add `--no-judge`
for deterministic checks only; otherwise cited paragraphs use the existing source/judge path.

## Design notes

- A CRITICAL ref page routes the case to admin review but does not change the editor trust delta; only the editor's own diff does. This is intentional.

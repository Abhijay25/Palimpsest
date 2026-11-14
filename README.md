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
GEMINI_THINKING_LEVEL=LOW     # optional: MINIMAL|LOW|MEDIUM|HIGH|XHIGH

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
`lang_code` is `en` or `fi` (the Stage 0 watch-lists). `audit-diff` returns 503 when
no `GEMINI_API_KEY` is set and Stage 0 is not clean (no verdict is faked), 502 if the
judge call fails. `editor_trust_delta` is a placeholder rule (FLAG_G1 -0.10, G2 -0.05,
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

## Design notes

- A CRITICAL ref page routes the case to admin review but does not change the editor trust delta; only the editor's own diff does. This is intentional.

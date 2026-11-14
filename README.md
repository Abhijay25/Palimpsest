# Palimpsest
HackJunction 2026 Project

## Switching to Gemini

The default judge backend is the Claude-subagent file exchange. To judge through
the Gemini API instead, set the key in `.env` (never commit it) and pass one flag:

```
GEMINI_API_KEY=...            # required
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

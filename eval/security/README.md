# Security end-to-end evaluation

This fixture set probes the running audit API's handling of hidden edit text,
hidden cited-page text, and citation lifecycle failures. It does not call the
internet itself. The API process must be able to reach the local fixture server
on the same host.

In separate terminals, run:

```sh
uv run python eval/security/poison_server.py --port 8799
uv run python eval/security/build_cases.py --port 8799
PALIMPSEST_USE_GEMINI=1 uv run uvicorn palimpsest.api:app --port 8765
uv run python -I eval/security/run_e2e.py --cases eval/security/cases/*.jsonl --out eval/security/runs/local
```

Use `--api URL` on the last command when the audit API is not at its default
`http://127.0.0.1:8765/api/v1/audit-diff`. The runner always exits zero: inspect
`table.md` for per-bucket hit/miss/false-positive counts and `misses.md` for the
expected kinds, returned kinds, API errors, and flag reasons.

The rot cases deliberately include a slow endpoint and a non-resolving host, so
the API's own bounded timeouts and public-address guard are part of what this
evaluation measures.

The local `rot-moved` fixtures expect no flag: content drift is evaluated only
with `PALIMPSEST_A1_DRIFT=1` against public URLs that have a Wayback baseline.

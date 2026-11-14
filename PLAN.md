# Palimpsest: module ownership and integration checklist

Specs: `wikipedia_bias_osint_verification_spec.md` (verifier) and
`stealth_ai_poisoning_dom_scanner_spec.md` (stealth scanner). Shared contracts live in
`palimpsest/schema.py` (`AuditOutput`, `AtomicProposition`, flagged spans, `Verdict`),
`palimpsest/stealth/models.py` (`ScanResult`) and `palimpsest/api.py`
(`AuditDiffResponse`, a superset of the spec's response fields).

## Modules

| Area | Owner module | Status |
|---|---|---|
| Stage -1 stealth scan (diff + cited pages) | `stealth/sanitizer.py`, `stealth/scanner.py`, `stealth/triage.py` | done |
| Pillar 3 render diff (DOM vs visible) | `stealth/render.py`, `stealth/pillar3.py`, `render_service.py` | done (concurrent, cannot block a verdict) |
| Vision / OCR layer | `stealth/vision.py` | evidence only, never escalates alone (4/8 real pages false-flagged) |
| Stage 0 prefilter | `stage0.py`, `wordlists.py` | done |
| Stage 1 source window (Exa + cache) | `sources.py`, `pipeline.py` | done; JSON cache, not MariaDB vector (see below) |
| Stage 2 judge (G1/G2/G3, EXPAND_CONTEXT, rewrite) | `judge.py`, `prompts/stage2_v7.txt`, `cascade.py` | done; Gemini backend opt-in |
| Edit segmentation, reasons, routing | `segment.py`, `reasons.py`, `api.py` | done |
| Cross-lingual cold path (`langlinks`) | `crosslingual.py`, `POST /api/v1/cross-lingual` | done; never called from the hot path |
| Single-edit diagnostic CLI | `diagnose.py` (`python -m palimpsest diagnose`) | done; same code path as audit-diff |
| Spec benchmark cases | `eval/cases/spec_benchmark.jsonl`, `eval/stealth/cases/spec_benchmark.jsonl` | cases written (5 + 7); not yet judged |

## Integration checklist

- [x] Stealth scan runs before Stage 0/1/2 on the diff; cited pages scanned concurrently.
- [x] Language-neutral rules only; en/fi watch lists add reasons, never decide alone.
- [x] Gemini is used only with `GEMINI_API_KEY` and `PALIMPSEST_USE_GEMINI=1`.
- [ ] Live Gemini end-to-end run (waiting for the go-ahead to use the key).
- [ ] Re-fit routing thresholds (0.70 admin / 0.45 review) on Gemini outputs.
- [ ] Spec latency budget: `<350 ms` hot path is not reachable with an LLM judge per edit;
      measure Gemini latency first, then decide what the hot path returns.

## Deliberately deferred

- MariaDB vector cache: the JSON file cache meets MVP needs; a database adds ops cost
  without improving accuracy until there is multi-instance deployment.

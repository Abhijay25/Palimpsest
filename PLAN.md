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

## Decisions API (`gemini-decision-1`): under review

The specs give it two roles. Neither is in the running pipeline, and this key cannot access the model.
- Verifier rubric classifier (a second call per edit): not built. One Hydrogen call already returns verdict, spans and rewrite (14/14 on the g02 set at HIGH), so a second classifier would add a call per edit with no measured accuracy gap to close. Remove unless a gap appears.
- Stealth triage of hidden-channel items: needed (s05ml: the deterministic layer escalates 4/23 attacks alone, triage the other 19, 0/71 benign escalated), but any capable model can do it; Haiku stands in today. Candidates to test: gemini-3.5-flash-lite, Hydrogen LOW. `GEMINI_TRIAGE_MODEL` defaults to `gemini-decision-1` until then.

## Citation integrity (B2, A1): modules committed, not wired

- B2 `palimpsest/cherry_pick.py`: language-neutral evidence selection (cited chunk, source conclusion by position, closest chunks) + one Hydrogen LOW call. No English discourse-marker lists (no-language-tricks rule).
- A1 `palimpsest/citation_lifecycle.py`: snapshots in SQLite with history (MariaDB system-versioned DDL included), six drift states, Wayback baseline and simulated mutations. Live check on a stable SVT article (2021 snapshot vs now) reported SEMANTIC_RUGPULL at drift 0.47 and 4 hidden-text vectors: whole-page raw-HTML comparison with the offline hashing embedder is noise. Before A1 can route anything: compare only the claim's discourse window (Stage 1 selection) on both versions, real embeddings, and a Hydrogen "still supports the claim?" check as the deciding signal.

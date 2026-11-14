# Bias Detector MVP — Design

Date: 2026-11-14 (Junction 2026, day 2). Parent spec: `~/Downloads/wikipedia_bias_osint_verification_spec.md` (sections 5, 6, 10, 11 are the relevant ones).

## Intent

The diff-verification engine (Stage 0 → 1 → 2) will be the basis for automatically flagging edits to Wikipedia admins. Before building anything on top of it (MariaDB, API, OSINT, cross-lingual), find out how well it actually detects the three violation categories, and what needs improving. Get an MVP running ASAP, then iterate (run → inspect → fix → re-run) until the user's Claude usage limits are hit.

## Goals

1. A Python pipeline implementing Stage 0 (zero-fetch pre-filter), Stage 1 (Exa source-window retrieval with local cache), Stage 2 (LLM judge using the parent spec's §10 prompt and JSON schema), with the judge behind a swappable backend interface.
2. A test set in English (primary — the user verifies outputs by reading them) and Finnish (best effort, each case carries an English gloss).
3. A run report the user can read case-by-case and that surfaces where the detector is wrong or unsure.
4. Iteration: each run's findings drive prompt/Stage 0 changes, re-run on the same cases, compare runs.

## Non-goals (this MVP)

MariaDB, FastAPI endpoints, editor trust/BLOC/OSINT, cross-lingual fan-out, community-notes rewrite consensus, visual citations, Nemotron.

## Anti-goals (failure even if it "works")

- **High false-positive rate on clean edits.** This feeds admins automatically; flagging good-faith edits is the worst outcome. Clean controls are mandatory in every run and the clean-flag rate is a headline metric.
- **Judging by world knowledge** instead of the cited source (breaks the spec's zero-parametric-knowledge rule).
- Results the user cannot verify by reading.

## Constraints (decided by user)

- **Language: Python** (latency is network-bound; tooling fits; matches spec's FastAPI). uv, Python 3.12, mypy strict, ruff, Pydantic models — no `Dict[str, Any]`.
- **Judge models for now: Haiku and Sonnet via Claude Code subagents on the user's subscription** — no Anthropic API key. Gemini key comes later; the backend interface must let a Gemini (or other API) backend drop in without touching stages or scoring.
- **Only Exa key available.** Token/usage conscious: batch cases per subagent, avoid re-judging unchanged cases.
- No formal ground truth required: English outputs are verified by the user reading them; Finnish is best effort.

## How it works

### Pipeline (`palimpsest/` package)

- **Stage 0** — deterministic. Normalise wikitext markup/whitespace/case/punctuation; `CLEAN_PASS` only if no token change survives normalisation *and* no number, negation, quantifier, or watch-list word (WP:WTW/WP:SAID lists, causal/motive markers — EN and FI lists) changed. Must be conservative: when unsure, pass to Stage 1.
- **Stage 1** — for each ref URL: cache lookup (JSON files keyed by URL hash, in a gitignored cache dir) → Exa `/contents` on miss → locate the sentence best matching the edited text → 7-sentence discourse window (±3 sentences + nearest heading). If the source is unreachable/paywalled, record `source_unavailable` and still run Stage 2 with that stated in the prompt (framing can still be judged from the diff). *(Builder's call how to rank sentences — simple lexical overlap is fine.)*
- **Stage 2** — the judge. Prompt = spec §10 system prompt + case payload. Output validated against Pydantic models mirroring the §10 schema; invalid output is retried once, then recorded as an error. Prompts are versioned files (`prompts/stage2_v1.txt`, …) and every result records the prompt version and model.
- **Judge backends**: one interface (`judge(cases) -> results`). MVP backend = *file exchange*: Python writes batch prompt files; Claude Code (the main session) dispatches Haiku and Sonnet subagents that read a batch and write result JSONL; Python ingests and validates. Batches of ~10 cases per subagent.
- **`EXPAND_CONTEXT`**: re-run the case with a wider window (±1,500 tokens) through Sonnet — this is the slot Nemotron had in the spec; it stays model-agnostic.
- **Latency**: Stage 0 and Stage 1 timings are measured and reported. Stage 2 latency through subagents is not meaningful and is not reported until a real API backend exists.

### Test set (`eval/cases/*.jsonl`)

Each case: id, lang, provenance, old_text, new_text, ref_urls, optional fixed source_window (for synthetic cases), expected label (or `UNLABELLED` for real edits), en_gloss (FI only), notes.

First iteration target: ~40 English, ~20 Finnish.

| Bucket | Lang | Source | Expected label |
|---|---|---|---|
| Spec benchmark cases 1–5 | EN | spec §11, hand-written source windows | known |
| Synthetic corruptions (G1 flips, G3 motive insertions, G2 verb/intensifier swaps) of clean paragraphs + their real refs | EN, FI | EN Wikipedia; FI from MariaDB dataset S | known |
| WNC framing pairs (old = neutralised, new = biased) | EN | Wiki Neutrality Corpus | G2 (no source window; noted as a limitation) |
| Real edits reverted with NPOV/POV/SYNTH-type edit summaries | EN | MediaWiki API | UNLABELLED (user reads) |
| Real reverted POV edits | FI | MariaDB dataset M (edit summaries + text hashes identify reverts) | UNLABELLED |
| **Clean controls**: real good-faith edits that survived, + untouched paragraphs | EN, FI | MediaWiki API / dataset M | CLEAN_PASS |

### Report (`eval/runs/<timestamp>/`)

- `results.jsonl` (machine-readable, per case per model).
- `report.html` (local, static): headline metrics, then one card per case — old/new diff, source window, Haiku and Sonnet verdicts side by side with flagged spans highlighted, propositions + entailment, rewrite, EN gloss for FI. Sorted so the interesting cases come first: wrong-vs-expected, Haiku≠Sonnet, flagged clean controls, `EXPAND_CONTEXT`.
- Metrics: per-category precision/recall on labelled cases, clean-control flag rate, Haiku–Sonnet agreement, Stage 0 exit rate (and any Stage 0 false passes), `EXPAND_CONTEXT` rate, source-unavailable rate, Stage 0/1 latency.
- `findings.md`: what went wrong, hypothesised cause, change made for the next run. A run-to-run comparison shows which cases changed verdict.

## Decisions settled after review (Claude's calls unless marked)

- **Pass bar (user)**: ≤5% of clean controls flagged and ≥80% of planted (labelled) violations caught. A prompt/Stage 0 change counts as an improvement only if it moves toward this bar without regressing the other side.
- **Future backends (user)**: Gemini Hydrogen (judge + Exa-driven retrieval) and the Gemini Decisions API as a fast 3-category classifier. The backend interface must allow a classify-only backend (verdict + confidence, no propositions/rewrite) alongside the full-JSON one, so the two can be compared on the same cases.

- **What counts as a flag**: any `FLAG_G1/G2/G3` verdict. `EXPAND_CONTEXT` is counted separately as an abstention, not a flag (it would route to escalation, not to an admin). Category mismatch (e.g. expected G3, got G2) counts as "flagged, wrong category" — tracked separately from missed.
- **Schema**: the §10 output schema is a fixed contract (Teammate 2 consumes it). Extra metadata (case id, model, prompt version, `source_unavailable`, timings, EN gloss) lives in a wrapper record around the model output, never inside it.
- **Real edits without a usable source**: kept, judged with `source_unavailable` stated in the prompt. Sampling prefers edits touching a sentence that carries a `<ref>`; no-source cases capped at ~1/3 of each real-edit bucket.
- **Datasets**: downloaded from the GitHub releases of `MariaDB/mariadb-wikipedia-datasets` (S: current fi/sv/en Markdown; M: every fi version as wikitext with editor, edit summary, text hash) into gitignored `data/`. No MariaDB server needed — read the files directly.
- **Subagent judging is two-phase and not unattended**: `prepare` (Stage 0+1, write batch prompt files) → main Claude Code session dispatches Haiku/Sonnet subagents per batch → `ingest` (validate, score, report). Resumable: completed batches are skipped.
- **Exa usage**: cache-first; ~60 cases × ~2 refs ≈ 120 calls per fresh set, near zero on re-runs.

## Left to the builder

Package layout details, sentence splitting/ranking approach, exact watch-lists, HTML styling, how the WNC and real-revert samples are drawn (random within filters; seeded), dataset download location (gitignored `data/`).

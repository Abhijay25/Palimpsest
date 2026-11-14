# Bias Detector MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Stage 0→1→2 diff-verification pipeline over an English + Finnish test set and produce a readable report showing how well it detects G1/G2/G3 violations and how often it flags clean edits.

**Architecture:** `palimpsest/` Python package: deterministic Stage 0, Exa-backed Stage 1 with JSON-file cache, Stage 2 judge behind a backend protocol. The MVP backend is two-phase file exchange: `prepare` writes batch prompt files, the main Claude Code session dispatches Haiku/Sonnet subagents that write result JSONL, `ingest` validates, scores and renders `report.html`. Test cases are built by scripts in `eval/build/` into `eval/cases/*.jsonl`.

**Tech Stack:** Python 3.12, uv, pydantic v2, httpx (async), mwparserfromhell, pyarrow, python-dotenv, pytest, mypy (strict), ruff.

**Spec:** `docs/superpowers/specs/2026-11-14-bias-detector-mvp-design.md` (parent: `~/Downloads/wikipedia_bias_osint_verification_spec.md` §5, §6, §10, §11).

## Global Constraints

- mypy strict, 0 errors; `ruff format` + `ruff check` clean. No `Dict[str, Any]`; Pydantic models or TypedDicts.
- The §10 output JSON schema is a fixed contract; extra metadata lives in a wrapper record.
- Verdicts: `CLEAN_PASS | FLAG_G1_FACT | FLAG_G2_FRAMING | FLAG_G3_MOTIVE | EXPAND_CONTEXT`. Flag = any `FLAG_*`. `EXPAND_CONTEXT` = abstention.
- Pass bar: ≤5% clean controls flagged, ≥80% labelled violations caught.
- Secrets from `.env` (`EXA_API_KEY`), never hardcoded. Data in gitignored `data/`, Exa cache in gitignored `cache/`, runs in `eval/runs/` (commit `report.html`/`findings.md`, not raw batches).
- Network access only at system boundaries (Exa, MediaWiki, HF/GitHub downloads) with explicit error handling; unit tests never hit the network (use `httpx.MockTransport`).
- MediaWiki API requests send a descriptive `User-Agent` (`Palimpsest-MVP/0.1 (hackathon research)`), no email.
- Commit after each task, one-line imperative message, no co-author tags.

## Review Focus

1. Exa returns 4xx/paywall/empty text → `SourceWindow(status="unavailable")`, pipeline continues (test in Task 3).
2. Edit only swaps a `<ref>` URL (citation swap) → Stage 0 must NOT clean-pass (test in Task 2).
3. Finnish inflection: watch-list hits must match inflected forms (`väitti`, `väittää`, `väitetysti`) → stem-prefix matching for `fi` (test in Task 2).
4. Model output that isn't valid §10 JSON, or `exact_substring` not found in `new_text` → recorded as `parse_error` / span shown unhighlighted, never a crash (test in Task 5).
5. Pure insertion (`old_text == ""`) or pure deletion → handled by Stage 0 (not clean) and the judge payload (test in Task 2).

---

### Task 1: Scaffold + schema

**Files:** Create `pyproject.toml`, `palimpsest/__init__.py`, `palimpsest/schema.py`, `tests/test_schema.py`, `.claude-project-map`, `.claude-requirements`.

**Interfaces — Produces (`palimpsest/schema.py`):**
- `Verdict(StrEnum)`, `ClauseType(StrEnum)`, `Entailment(StrEnum)`, `Guideline(StrEnum)` — values exactly as §10.
- `AtomicProposition`, `FlaggedSpan`, `AuditOutput` — §10 fields exactly (`verdict, confidence: float, expand_direction, atomic_propositions, flagged_spans, neutral_rewrite: str | None`).
- `ExpectedLabel = Verdict | Literal["UNLABELLED"]`
- `Case(BaseModel)`: `case_id, lang: Literal["en","fi"], bucket: str, provenance: str, page_title: str, old_text: str, new_text: str, ref_urls: list[str], source_window: str | None = None, expected: ExpectedLabel, en_gloss: str | None = None, notes: str = ""`.
- `SourceWindow(BaseModel)`: `url: str | None, status: Literal["ok","unavailable","fixed"], text: str, latency_ms: float`.
- `CaseResult(BaseModel)` (wrapper): `case_id, model: str, prompt_version: str, stage_reached: int, stage0_ms: float, stage1_ms: float, source_status: str, output: AuditOutput | None, parse_error: str | None`.
- `load_cases(path: Path) -> list[Case]`, `dump_jsonl(path: Path, rows: Sequence[BaseModel]) -> None`.

- [ ] Step 1: `uv init`-style `pyproject.toml` (package `palimpsest`, deps above, `[tool.mypy] strict = true`, pytest dev dep). `uv sync`.
- [ ] Step 2: Test `test_audit_output_roundtrip` (parse the §10 example with one proposition and one span; assert `verdict == Verdict.FLAG_G3_MOTIVE`) and `test_audit_output_rejects_unknown_verdict` (raises `ValidationError`).
- [ ] Step 3: Implement schema. Run `uv run pytest`, `uv run mypy .`, `uv run ruff check .` → all pass.
- [ ] Step 4: Write `.claude-project-map` (file → responsibility) and `.claude-requirements` (decisions from the design doc, one line each). Commit `Scaffold package and audit schema`.

### Task 2: Stage 0 pre-filter

**Files:** Create `palimpsest/wordlists.py`, `palimpsest/stage0.py`, `tests/test_stage0.py`.

**Interfaces — Produces:** `Stage0Result(BaseModel)`: `clean: bool, reasons: list[str], latency_ms: float`; `prefilter(old_text: str, new_text: str, lang: Literal["en","fi"]) -> Stage0Result`; `extract_ref_urls(wikitext: str) -> list[str]`; `strip_wikitext(wikitext: str) -> str` (mwparserfromhell `strip_code`, refs removed).

Approach: normalise (strip markup, lowercase, collapse whitespace, drop punctuation) → token multiset diff. Not clean if ANY of: normalised tokens differ beyond a single-token edit with Levenshtein ≤2 between tokens of the same length class (typo fix); a number changed; a negation/quantifier/watch-list/causal-marker token appears in the added or removed tokens; `extract_ref_urls` sets differ; either side empty. Watch-lists (EN and FI) per §5: neutral reporting verbs, factive verbs, doubt verbs, scalar intensifiers/downplayers, motive markers, negations, quantifiers. FI matching = prefix match on stems (e.g. `väit`, `myön`, `paljast`, `jotta`, `ei `, `kaikki`).

- [ ] Step 1: Tests: `test_typo_fix_is_clean` ("recieved"→"received"), `test_punctuation_markup_is_clean` (`[[Helsinki]]` → `Helsinki`, added comma), `test_number_change_not_clean` (3.2%→5.2%), `test_negation_not_clean` (spec Case 2 texts), `test_factive_verb_swap_not_clean` ("stated"→"admitted"), `test_ref_url_swap_not_clean` (same prose, different `<ref>` URL), `test_insertion_not_clean` (old=""), `test_fi_inflected_doubt_verb_not_clean` ("sanoi"→"väitti").
- [ ] Step 2: Run → fail. Step 3: implement. Step 4: run tests + mypy + ruff → pass. Commit `Add Stage 0 pre-filter`.

### Task 3: Stage 1 source windows

**Files:** Create `palimpsest/sources.py`, `tests/test_sources.py`.

**Interfaces — Produces:** `class SourceFetcher` with `__init__(self, api_key: str | None, cache_dir: Path, client: httpx.AsyncClient | None = None)` and `async def window(self, url: str, claim: str, radius: int = 3) -> SourceWindow`; module function `discourse_window(text: str, claim: str, radius: int = 3) -> str`.

Approach: cache file `cache/exa/<sha256(url)>.json` holding full text. Miss → `POST https://api.exa.ai/contents` with header `x-api-key`, body `{"urls": [url], "text": true}`; text = `results[0].text`. Sentence split with a regex on `[.!?]\s+` (good enough for EN/FI). Best sentence = max token-overlap with `claim`; window = best ±`radius` sentences, prefixed by the nearest preceding Markdown heading line if any. Any HTTP error, timeout (10 s), missing key, empty text, or text < 200 chars → `status="unavailable"`, `text=""`.

- [ ] Step 1: Tests with `httpx.MockTransport`: `test_window_centres_on_best_sentence` (10-sentence text, claim matches sentence 6 → window is sentences 3–9), `test_cache_hit_skips_network` (second call: transport asserts not called), `test_http_404_is_unavailable`, `test_missing_key_is_unavailable`, `test_short_text_is_unavailable`.
- [ ] Step 2–4: fail → implement → pass (+ mypy, ruff). Commit `Add Exa source window retrieval`.

### Task 4: Stage 2 prompt + file-exchange judge + pipeline CLI

**Files:** Create `palimpsest/prompts/stage2_v1.txt` (spec §10 prompt verbatim), `palimpsest/prompts/subagent_judge.txt`, `palimpsest/judge.py`, `palimpsest/pipeline.py`, `palimpsest/__main__.py`, `tests/test_judge.py`.

**Interfaces:**
- Consumes: `Case`, `prefilter`, `SourceFetcher.window`, `CaseResult`, `AuditOutput`.
- Produces: `class JudgeBackend(Protocol)` with `name: str`; `class FileExchangeBackend` with `write_batches(self, prepared: list[PreparedCase], run_dir: Path, models: list[str], batch_size: int = 10) -> list[Path]` and `read_results(self, run_dir: Path, model: str) -> dict[str, AuditOutput | str]` (str = parse error); `PreparedCase(BaseModel)`: `case: Case, stage0: Stage0Result, window: SourceWindow | None`; `render_case_payload(pc: PreparedCase) -> str`; `async def prepare(cases_paths: list[Path], run_dir: Path, models: list[str]) -> None`.
- CLI: `uv run python -m palimpsest prepare --cases eval/cases/*.jsonl --run eval/runs/<id> --models haiku sonnet` (the `ingest` subcommand is added in Task 5).

Payload per case: `OLD_TEXT`, `NEW_TEXT`, `CITATION_DISCOURSE_WINDOW` (or the literal line `SOURCE UNAVAILABLE — judge framing from the diff only; do not flag G1/G3 for lack of a source`), `DOMAIN_TRUST_TIER: UNKNOWN`. Stage-0-clean cases get a synthetic `CLEAN_PASS` result and are NOT written to batches. Batch file `run_dir/batches/<model>/batch_NNN.md` = `subagent_judge.txt` (instructions: read only this file, output one JSON line per case `{"case_id": ..., "output": <§10 JSON>}` to `run_dir/results/<model>/batch_NNN.jsonl`, nothing else) + `stage2_v1.txt` + payloads. `prepare` also writes `run_dir/prepared.jsonl` and `run_dir/manifest.json` (prompt_version, models, case files). Resumable: `write_batches` skips batches whose result file exists.

- [ ] Step 1: Tests: `test_stage0_clean_cases_skip_batches`, `test_batch_contains_prompt_and_payloads` (batch text contains "CRITICAL GROUNDING RULE" and both case_ids), `test_unavailable_source_payload_line`, `test_read_results_invalid_json_is_parse_error`, `test_read_results_valid_line_parses`.
- [ ] Step 2–4: fail → implement → pass (+ mypy, ruff). Commit `Add Stage 2 prompt, file-exchange judge and CLI`.

### Task 5: Scoring + HTML report

**Files:** Create `palimpsest/scoring.py`, `palimpsest/report.py`, `tests/test_scoring.py`.

**Interfaces — Produces:** `Metrics(BaseModel)` per model: `n, labelled_n, violation_recall: float` (expected FLAG_* → got any FLAG_*), `category_accuracy: float` (expected FLAG_X → got FLAG_X), `clean_flag_rate: float` (expected CLEAN_PASS → got FLAG_*), `abstain_rate, parse_error_rate, stage0_exit_rate, stage0_false_pass: int` (expected FLAG_* but stage-0 clean), `source_unavailable_rate, stage0_ms_p50, stage1_ms_p50`, `confusion: dict[str, dict[str, int]]`, `passes_bar: bool`; `agreement(results_a, results_b) -> float`; `score(prepared: list[PreparedCase], results: dict[str, list[CaseResult]]) -> dict[str, Metrics]`; `render_report(run_dir: Path, prepared, results, metrics, compare_to: Path | None = None) -> Path`; `ingest(run_dir: Path, compare_to: Path | None = None) -> None` in `pipeline.py` (reads prepared + results, scores, renders) and CLI `uv run python -m palimpsest ingest --run eval/runs/<id> [--compare eval/runs/<prev>]`.

Report: one static HTML file, inline CSS, light/dark via `prefers-color-scheme`. Header = metrics table per model + pass-bar badge. Cases sorted: wrong-vs-expected → Haiku≠Sonnet → flagged clean controls → EXPAND_CONTEXT → rest. Each card: id, bucket, lang, Wikipedia link if any, old/new word diff (`difflib`, ins/del styling), source window (collapsed), per-model verdict + confidence, flagged spans highlighted in new_text (unmatched spans listed below), propositions table, rewrite, EN gloss. HTML-escape all text. `compare_to` adds a "changed since previous run" section listing case_ids whose verdict changed.

- [ ] Step 1: Tests: `test_clean_flag_rate` (2 clean expected, 1 flagged → 0.5), `test_recall_counts_wrong_category_as_caught`, `test_parse_error_excluded_from_recall_denominator_but_counted`, `test_report_escapes_html` (new_text `<script>` appears escaped), `test_span_not_in_text_listed_not_crash`.
- [ ] Step 2–4: fail → implement → pass (+ mypy, ruff). Commit `Add scoring and HTML report`.

### Task 6: Test-set builders (independent; run in parallel by subagents)

All write `Case` JSONL to `eval/cases/`, seeded (`random.Random(1114)`), and are committed with their output. Builders in `eval/build/`. Each builder dedupes and drops cases where `strip_wikitext(new_text)` is > 1,500 chars (trim to the changed paragraph first).

- **6a `spec_cases.py` → `en_spec.jsonl`** (5 cases): spec §11 Cases 1–5 with hand-written `source_window` (`status="fixed"`), expected CLEAN_PASS, G1, G2, G3, EXPAND_CONTEXT.
- **6b `en_wnc.py` → `en_wnc.jsonl`** (10 cases): HF `reza-alipour/WNC` `data/test-00000-of-00001.parquet` (columns `text` = biased, `edited_text` = neutral). `old_text = edited_text`, `new_text = text`, `source_window = edited_text` (fixed; noted as self-source limitation), expected `FLAG_G2_FRAMING`. Plus 3 controls where `old_text = new_text = edited_text` with a typo injected into old → expected CLEAN_PASS.
- **6c `en_reverts.py` → `en_reverts.jsonl` (10 UNLABELLED) + `en_controls.jsonl` (10 CLEAN_PASS)**: MediaWiki API `list=recentchanges`, `rcnamespace=0`, `rctag=mw-undo` then `mw-rollback`/`mw-manual-revert`, comment regex `(?i)\b(n?pov|neutral|synth|original research|editoriali[sz]|puffery|peacock|weasel|undue|biased)\b`. Reverted rev = the undo's `old_revid`; before = its parent. Fetch wikitext (`prop=revisions&rvslots=main&rvprop=content`), pick the changed paragraph via `difflib` on `\n\n`-split paragraphs, `ref_urls = extract_ref_urls(new_paragraph)`, texts via `strip_wikitext`. Controls: edits ≥7 days old, not tagged `mw-reverted`, `!bot`, |sizediff| 30–600, comment not matching revert words, prefer paragraphs carrying a `<ref>`. Cap no-ref cases at ~1/3. Expected for controls = CLEAN_PASS (assumption: surviving edit ≈ clean; noted).
- **6d `fi_dataset_m.py` → `fi_reverts.jsonl` (8 UNLABELLED) + `fi_controls.jsonl` (6 CLEAN_PASS)**: download `versions-01.parquet` and `versions-02.parquet` from release `m-2026-10` into `data/`, verify against `SHA256SUMS`. Revert = version *i* whose `sha1` equals version *i−2*'s: reverted = *i−1*, before = *i−2*. Filter reverting comment `(?i)(n?pov|puolueet|näkökulm|mielipi|spekul|tulkin|lähteet|wp:ei|wp:ttt)` (if <8 hits, relax to any revert whose diff adds ≥5 words). Controls: registered user, not minor, no revert within the next 10 versions, 30–600 byte change. Same paragraph/ref extraction as 6c.
- **6e `fi_synthetic` + `en_synthetic` → `fi_synthetic.jsonl` (12), `en_synthetic.jsonl` (12)**: sample paragraphs (3–6 sentences) from dataset S `articles-fi.parquet` / `articles-en.parquet` (release `s-2026-10`). A Sonnet subagent writes, per language: 3× G1 (negation/quantifier/number flip), 3× G2 (factive/doubt verb or intensifier), 3× G3 (unsupported motive clause), 3× meaning-preserving paraphrase (expected CLEAN_PASS — the false-positive test). `old_text` = one original sentence, `new_text` = edited sentence, `source_window` = whole original paragraph (`fixed`). Subagent output is validated by loading through `load_cases`.
- **6f FI glosses**: a Sonnet subagent adds `en_gloss` ("OLD: … / NEW: …" literal translation) to every `fi_*.jsonl` case.

- [ ] For each: run builder, `uv run python -c "from palimpsest.schema import load_cases; ..."` loads the file and prints count matching the target. Commit `Add <bucket> test cases` per builder.

### Task 7: First run

- [ ] Step 1: Ensure `EXA_API_KEY` is set in `.env` (user fills it). If absent, run anyway: ref-based cases become `unavailable` and that is reported.
- [ ] Step 2: `uv run python -m palimpsest prepare --cases eval/cases/*.jsonl --run eval/runs/r01 --models haiku sonnet`.
- [ ] Step 3: Main session dispatches one subagent per batch file (`model: haiku` / `model: sonnet`), prompt: "Read <batch path> and follow it exactly." Parallel within a model.
- [ ] Step 4: `uv run python -m palimpsest ingest --run eval/runs/r01` → `report.html`. Open it; write `eval/runs/r01/findings.md` (top failure patterns, hypothesised cause, change for r02). Commit `Add first evaluation run`.
- [ ] Step 5: Iterate: new prompt version (`stage2_v2.txt`) or Stage 0 rule change → new run with `compare_to` → findings → commit. Repeat until usage limits.

## Known caveat (put in every findings.md)

Subagent judges run inside Claude Code with its own system prompt and tool access, not a bare API call, so verdict quality is indicative, not identical to an API backend. Stage 2 latency is not measured until an API backend exists.

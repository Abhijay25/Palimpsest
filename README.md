# Palimpsest
HackJunction 2026 Project

Local MediaWiki infrastructure for the team, with separate Finnish, Swedish and English wikis and one persistent MariaDB server. The approved baseline includes Vector 2022, local accounts, source/visual editing, history/diffs, discussions, watchlists, uploads, references, Lua and online Commons. See the [scope](docs/infra/spec.md) for the feature matrix and boundaries.

## Start locally

Install Docker Desktop (or Docker Engine with Compose) and Python 3.11+. Run from a clone of this repository:

```sh
python3 scripts/wiki setup
python3 scripts/wiki verify --scope runtime
```

Open Finnish at <http://127.0.0.1:8081>, Swedish at <http://127.0.0.1:8082> and English at <http://127.0.0.1:8083>. Setup initializes empty functional wikis; downloading or importing the dataset is separate. Initial pulls and online Commons require internet.

Generated databases, uploads, configuration and credentials live in ignored `.local/wiki`. Each wiki has a local `admin` account; its generated password is in `.local/wiki/secrets/<language>/admin-password`. Keep these local files private. New accounts can also be created through the wiki UI.

```sh
python3 scripts/wiki down       # stop; preserve data
python3 scripts/wiki up         # restart
python3 scripts/wiki update     # run schema updates
```

For a separate environment, put all shared options before the command:

```sh
python3 scripts/wiki --project teammate --data-root /path/to/wiki-data --ports 9081,9082,9083 setup
```

Reuse the same options for later commands. `reset --confirm-project <name>` deletes only that named runtime's databases, configuration, credentials and uploads; it preserves acquired source datasets/history. Read [verification quickstart](docs/infra/quickstart.md) for platform/resource details and isolated test commands.

## Dataset and original history

Downloaded content retains the release README and its notices: Wikipedia text is CC BY-SA 4.0, with credit and original article links retained in the source manifests. Consult the fetched `dataset/raw/README.md` and the [release](https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/tag/s-2026-10).

The locked `s-2026-10` release contains 29,460 pages: 19,285 Finnish, 4,921 Swedish and 5,254 English. Its Markdown snapshots are research assets; they are not a MediaWiki SQL backup or the original edit histories.

```sh
python3 scripts/wiki dataset fetch
python3 scripts/wiki history probe-anchors
python3 scripts/wiki history acquire --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data support --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data import --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki verify --scope sample --sample-manifest tests/data/fixtures/sample-corpus.json
```

These commands use an explicit six-page real sample, with original public histories through each S revision anchor. Dependency acquisition is budgeted and resumable; incomplete dependencies/imports produce a nonzero result and an explicit report. Preserve the data root and rerun to resume. Source IDs and local IDs are recorded separately. See [pipeline instructions](infra/data/README.md) for reports, recovery and explicit full-corpus options.

**Full S import and complete original-history reconciliation are outstanding.** Runtime health or a passing sample does not certify full seeding. Use `verify --scope full` to expose missing full-corpus work; see [verification evidence](docs/infra/verification.md) for actual tested behavior and limitations.

## Development and checks

```sh
python3 -m unittest discover -s tests/runtime -v
python3 -m unittest discover -s tests/data -v
python3 -m unittest discover -s tests/infra -v
```

The test quickstart documents opt-in Docker/browser checks. Runtime images are pinned by multi-platform digest. No host PHP, database or data-science packages are required. Custom extensions can be mounted through `infra/wiki/extensions/load.php`, followed by `scripts/wiki update`; upstream MediaWiki core stays in its image.

The [specification](docs/infra/spec.md), [design](docs/infra/design.md), [contracts](docs/infra/contracts.md), [task plan](docs/infra/tasks.md) and [worker registry](docs/infra/orchestration.md) record the approved SDD process. This infrastructure does not implement the separate Wikipedia Blame prototype.

## Detector API (`palimpsest` Python package)


### Switching to Gemini

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

### API

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

### Live-page audit

`python -m palimpsest audit-page --lang sv --title Tornedalingar --max-paragraphs 12 --json report.json`
audits the current revision. It always scans the whole wikitext for stealth content
and checks rendered dates using month names supplied by that wiki's interface messages.
It also compares dates beside historical Wikipedia revision links. Add `--no-judge`
for deterministic checks only; otherwise cited paragraphs use the existing source/judge path.
`audit-diff` also renders only changed wikitext units containing a template or `<ref>`
against the target wiki, returning `citation_dates` (`ok`, `skipped`, or `unavailable`)
with any FUTURE_DATE or REVISION_DATE_MISMATCH findings; findings preserve the edit
verdict but route it to at least `review` with reason `CITATION_DATE`.

### Design notes

- A CRITICAL ref page routes the case to admin review but does not change the editor trust delta; only the editor's own diff does. This is intentional.

# Frozen implementation contracts — v1

Approved D1–D6 implementation baseline, 2026-11-14. Requirements remain in spec.md. Changes to these contracts require orchestrator coordination; material scope changes require owner review.

## Ownership and entry points

- A owns `infra/wiki/**`, `scripts/runtime.py`, `scripts/runtime/**` and runtime-specific unit tests under `tests/runtime/**`. A does not own dataset state or the main dispatcher.
- B owns `infra/data/**`, `scripts/data.py`, `scripts/data/**`, `datasets.lock.json`, and data-specific tests under `tests/data/**`. B alone writes bulk-data caches.
- C owns `tests/infra/**`, `.github/workflows/infra.yml`, and `docs/infra/quickstart.md`. C tests contracts independently and does not edit A/B implementation files.
- Orchestrator owns `scripts/wiki`, root README.md, .gitignore and docs/infra/* except quickstart.md. Workers propose changes to these in their handoffs.
- Namespace collisions must be avoided: do not simultaneously create a Python package and module with the same import name. Keep the two standalone entry scripts thin and internal packages distinctly named.

## Common CLI

Host prerequisites: Docker Desktop/Engine + Compose v2 and Python 3.11+. No host third-party Python dependencies. `scripts/wiki` is the public Python launcher (executable) and dispatches to the two standalone entry scripts. Docker credential helpers must resolve if Docker Desktop is outside PATH.

Every entry point accepts `--project NAME`, `--data-root PATH` and `--ports FI,SV,EN` before the command. Defaults: project `palimpsest`, ignored repo-local `.local/wiki`, ports 8081,8082,8083. Paths resolve absolutely; Docker project names/ports are validated. Do not resolve relative input against a container-only directory. Help must work without Docker running.

Runtime: `python3 scripts/runtime.py [common options] setup|up|down|status|logs|update|reset|manifest|exec`.
- `manifest` writes C1 atomically to `<data-root>/runtime.json` and prints its absolute path; no secrets in stdout/report.
- `exec --language LANG -- COMMAND...` invokes the selected wiki container without shell interpolation; it preserves the child exit code. This is the importer's maintenance bridge.
- `down` retains data; `reset --confirm-project NAME` only removes this project's disposable runtime state after exact confirmation. No implicit reset.
- `setup` is repeatable and initializes empty wikis, not the full corpus.

Data: `python3 scripts/data.py [common options] dataset fetch|history acquire|data import|verify`.
- `--sample-manifest PATH` is explicit and supported for history/import; it cannot silently change full mode.
- `verify --scope sample|full` writes C5; errors and incomplete required coverage return nonzero.
- Core parsing/acquisition/export logic must be separately importable for isolated tests. All third-party data dependencies execute in a pinned tooling container.
- Exit statuses: 0 successful requested operation, 1 operational/incomplete-coverage failure, 2 invalid CLI/configuration. Source-specific exceptions are recorded in C5, not swallowed.

## C1 runtime manifest, schema_version 1

Fields: `schema_version`, `project`, `data_root`, `ports` (fi/sv/en integer), `languages` (fi/sv/en objects with `api_url`, `service`, `database`), `versions` (resolved images/extension inventory), `initialized` (per-language boolean). Local API URLs bind localhost and point to the correct port. No passwords/tokens. Consumers validate version and expected project; uninitialized services cannot be reported ready.

## C2 corpus manifest, schema_version 1

Fields: `schema_version`, `release` (`repository`, `tag`, `assets` including URL/size/SHA-256), `scope` (`full` or `sample`), `expected_counts`, `articles`.
Article fields: `source_wiki` (`fiwiki`, `svwiki`, `enwiki`), `language`, `source_page_id`, `anchor_revision_id`, `title`, `source_url`, `wikidata_id` (nullable), `dataset_timestamp` (nullable). Source IDs are positive integers and keys include source_wiki. Missing timestamps cannot be fabricated. All original S fields remain available in raw locked assets.
Full expected counts: fi 19285, sv 4921, en 5254. Sample manifests retain the full release identity but explicitly enumerate only their selected keys and sample expected counts.

## C3 source history inventory, schema_version 1

History records: source_wiki, source_page_id, source_revision_id, source_parent_id (nullable), timestamp (UTC ISO8601), author (`kind`, `value`, `hidden`), comment (nullable), comment_hidden, minor, content_model, content_format, content (nullable), content_hidden, source_sha1 (nullable), computed_sha256 (nullable), source_url, acquisition_method, acquired_at, anchor_revision_id.

Retain missing/hidden distinctions, including genuinely empty text versus unavailable text. Store content outside manifests when needed; a `content_ref` may replace inline content if its bytes are verified. A source ID with conflicting content is a failure. Durable per-page state records continuation, committed batches, source checksums, anchor validation, enumeration exhaustion and unresolved gaps. Never advance continuation before the data it references is durable.

## C4 import manifest, schema_version 1

Each record keys source_wiki/source_revision_id and records source_page_id, source_parent_id, local_page_id, local_revision_id, source content hash, timestamp, author representation, batch checksum, status and errors. Source IDs never imply local IDs. Local parent mapping may differ where public source history has unavailable parents; retain and report that distinction. New local revisions have separate identity and must survive repeat imports.

## C5 coverage report, schema_version 1

Fields: schema_version, code_revision, project, scope, release, generated_at, runtime_ready, sample_verified, per_language, rendering, failures, complete.
Per-language fields: expected_articles, acquired_articles, imported_articles, reconciled_articles, expected_revisions (nullable until source enumeration is complete), acquired_revisions, imported_revisions, reconciled_revisions, unresolved_pages, unresolved_revisions.
`complete` requires the requested scope's exact expected membership, exhausted source enumeration through anchors, reconciled original records/mapping and zero unresolved required records. It is false/unknown while expected revision inventory is unknown; successful runtime health or a clean importer exit is insufficient. Rendering is separately reported and can remain incomplete even when source-history reconciliation passes.

Reports must distinguish an operational failure from an approved source exception; source exceptions are not silently added to success counts. Atomic writes and version validation apply to C1–C5. Independent tests must prove that a removed history or mapping makes the report fail.

## Integration handoff

Workers supply commit SHA(s), precise changed paths, commands/results, verified versus unverified claims and issues. Do not push or open a PR. A and B may proceed independently after receiving the committed baseline. C can implement fixtures after reading this contract; live integration waits for reviewed A/B work. The orchestrator resolves implementation details not specified here without widening product scope.

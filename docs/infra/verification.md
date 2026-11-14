# Infrastructure verification record

Status: infrastructure/sample acceptance passed on 2026-11-14, including independent Sol browser and restart verification. Full S seeding and complete rendering dependency coverage remain incomplete under approved D5.

## Reviewer, code and environment

- Actual orchestrator: `gpt-6.1-sol`, high reasoning, verified from session turn metadata. Three visible worker chats were each verified `gpt-6-luna`, high. IDs, worktrees and handoff exception are in [orchestration.md](orchestration.md) and [contracts.md](contracts.md).
- Approved SDD baseline: `e6d6e657ffe2a10bc7a598bc85f2ab1223741b7f`.
- Runtime producer last changed at integration commit `f3dabeb` (worker source `f371160`). Data producer last changed at `8a05280` (worker source `6d9a810`), including semantic integrity validation of cached article and supporting-revision text. The final browser candidate is `0b3564b54a40730c274c13de7463355555b6d1e6`; C source `de08ce0` has an identical harness. The built runner hash was audited independently; Sol ran the complete fresh-project suite successfully at this revision in 241.8 seconds; subsequent commits update documentation only.
- Observed host: macOS ARM64, Docker Desktop 4.63.0, Engine 29.2.1 Linux/arm64, Compose v5.0.2. Actual container runs here use Linux/arm64. Image index support for Linux/amd64 is verified metadata, not an amd64 execution result.
- Primary persistent manual-test environment: project `palimpsest`, repository `.local/wiki`, HTTP ports 8081/8082/8083. Generated state is ignored and excluded from Docker build contexts. Admin credentials remain in local private files and are not recorded here.
- Temporary integration project `palimpsest-integration`, data root `/private/tmp/palimpsest-integration-20261114`, was stopped with its data preserved after independent checks. B's source/probe evidence remains under `/private/tmp/palimpsest-b-data`. A, B and C retained test runtimes were shut down with their data/worktrees preserved. Sol disposable browser projects were removed only by their exact-project cleanup. The default `palimpsest` project remains running for human testing.

## Actual executed checks

| Scope | Result and evidence |
|---|---|
| Deterministic producers | Sol ran 29 data and 10 runtime tests successfully after the final data fix. |
| Independent oracle/dispatcher | Sol ran 18 infrastructure tests successfully; the additional Docker-gated test is skipped in ordinary invocation. These are semantic positive/negative fixtures and observed launcher behavior, not filename checks. |
| Image locks | Queried OCI indexes for MediaWiki, MariaDB, Python tooling and Playwright digests. All four contain Linux/amd64 and Linux/arm64 manifests. Runtime extension/version/dependency inventory ran against the actual pinned MediaWiki image. Undeclared extension versions remain explicitly unknown, with the bundled image identity recorded. |
| Fresh default setup | Ran the README's `python3 scripts/wiki setup` in a previously absent `.local/wiki`, after stopping the temporary integration project. All three wikis initialized and served their correct languages and wiki IDs. |
| Default dataset command | Reused completed public release files, then ran `scripts/wiki dataset fetch`: all ten locked assets reverified; the pinned PyArrow container rebuilt exact membership. No local DB, credentials or source/local mappings were copied between runtimes. |
| Independent raw membership audit | Separate read-only PyArrow audit matched every `(source wiki, page ID, anchor revision, title)` against the full C2 manifest: 29,460 unique keys, fi 19,285 / sv 4,921 / en 5,254. All ten file lengths and SHA-256 values matched the lock. |
| Original source truth | Queried public APIs for the complete six-page public revision inventory through each S anchor. Exact ID sets, parents, timestamps, public authors/comments/minor flags matched. Recomputed all retained text SHA-1/SHA-256 values. Total 148 revisions; zero source gaps. |
| Native import | Sol executed actual `importDump` into both temporary integration and default runtimes. All six articles / 148 revisions reconciled. Import returns nonzero while supporting inventories remain incomplete; that result is not mislabeled a complete rendering import. |
| Independent local history audit | A separate script queried every imported local revision and compared actual wikitext/hash, UTC timestamp, contributor, summary, minor flag, content model and mapped parent with source records. Passed all 148 in both runtimes, whose local IDs differ. Named imported users have the actual `Imported>` prefix. |
| Repeat import/local edit | Integration reimport recognized all six as already reconciled. A new local edit remained the same latest revision after another import, while all original records still matched without duplicates. |
| Source resume | Corrupt committed batches fail closed; checksum-valid orphan batches recover; interrupted gap analysis resumes; repeated continuation and retry exhaustion fail. Low-space fixture preserves a valid checkpoint and resumes after capacity returns. |
| Import crash window | Reviewed and reran the regression for DB commit before C4 reconciliation. B executed actual native import on three clearly synthetic, S-disjoint pages, then injected KeyboardInterrupt before C4 checkpoint. Resume reconciled the first page without reimporting it and imported the other two once. Six revision mappings/content/metadata verified. This is an injected interruption at a durable boundary, not an OS process-kill experiment. Evidence: B's `synthetic-crash-window/report.json`. |
| Rendering framework | Sol created explicitly synthetic nested-template, Scribunto, TemplateStyles and citation fixtures in all three integration wikis; actual parsed output matched each feature. These fixtures do not count as S articles or prove full historical rendering. |
| Online Commons | InstantCommons resolved Example.jpg in all three wikis. A bare Python GET returned external HTTP 403 and was not counted as success. Sol then observed the actual image loaded in IAB in English, Finnish and Swedish (`complete=true`, natural width 172). |
| Extension mount/schema workflow | Sol temporarily mounted a parser-hook fixture via documented `extensions/load.php`, ran the public update command and observed language-specific output in all three wikis. The loader was removed in a finally block. No product extension was shipped by this probe. |
| Background jobs | Sol stopped only the integration job services, edited transcluded templates, confirmed each stored article link inventory was still unchanged and three jobs were queued per language. Restarting those services produced the correct language-specific target links. Evidence: `sol-job-evidence.json` in temporary integration root. |
| Managed settings/language links | Repeated setup refreshed managed settings while preserving credentials and source data. Sol observed `skin-vector-2022`, valid branding, generic source-project/license footer and both correct local counterpart routes in all three wikis. B also checked new local users. |
| Offline false-green control | Sol shut down the default runtime, ran sample verification, observed exit 1 and a newly written C5 with all three endpoint failures, runtime_ready=false and complete=false. Restart and verification restored sample_verified=true and all 148 reconciled revisions. Evidence: `/private/tmp/palimpsest-sol-offline-coverage.json`. |
| Full-corpus false-green control | On a healthy sample runtime, full verification returned exit 1: 6 imported of 29,460 required, 29,454 unresolved pages and unknown full revision totals. Runtime readiness did not become full success. |
| Browser workflows | C passed actual account/login/logout, source+VisualEditor saves, search, history/diff, DiscussionTools post/reply, second-user watchlist, upload/display and anonymous protect boundary in all three languages. C and Sol independently passed all three languages and the down/setup persistence phase. Sol used a fresh isolated project at `0b3564b` with ports 39081–39083; actual exit 0, elapsed 241.8 seconds. Harness SHA-256 `6303ad34a1514b35f6244bfabc08192e393f9c86fb5bcc210dd2bfe4a1e155bc` matched the executed image. Logs: `/private/tmp/palimpsest-sol-browser-final3.log` and C's `/private/tmp/palimpsest-browser-final-c15.log`. |
| CI | Linux ordinary CI passed at final code `0b3564b` ([run](https://github.com/Abhijay25/Palimpsest/actions/runs/43547223472)). Ordinary CI runs isolated fixtures without downloading the full corpus; Docker/browser tiers are opt-in. |

## Sample and remaining coverage

| Language | Expected S pages | Acquired/imported sample pages | Original sample revisions |
|---|---:|---:|---:|
| fi | 19,285 | 2 | 62 |
| sv | 4,921 | 2 | 12 |
| en | 5,254 | 2 | 74 |
| Total | 29,460 | 6 | 148 |

`sample_verified=true` and `complete=true` apply only to an explicitly requested **sample** history scope. Rendering is separately incomplete. A full request remains `complete=false`; expected full revision totals are null until enumeration is exhausted. No full-corpus history acquisition was launched.

Real support traversal ran twice with a one-request budget, resumed its checkpoint and imported/reconciled two distinct supporting revisions. The remaining graph is explicitly unresolved; its title/version inventory is in C5 and supporting reports. This does not establish complete rendered output for the six real articles. Representative synthetic feature rendering passed. Exact historical pixels, full local media, M-dataset acceleration/overlap and full-corpus performance are not certified.

Original source records, source URLs, release README/license notices and source/local mappings are retained outside Git. The source project footer does not guess a verified source article from an arbitrary local title. The M dataset is not used by this implementation; public APIs provide all three languages through each selected anchor.

## Findings, repairs and retests

| Finding | Repair and verification |
|---|---|
| Project inventory exposed one representative folder, not every source root | Verified actual Git roots/remotes/baselines; explicit Palimpsest source root used for all workers. |
| Legacy skin, wrong job dependencies and weak health matching | Correct `vector-2022` key; per-language jobs; parsed language-aware API health. Actual HTML and queued-job behavior verified. |
| Installer confpath/credentials/script path and duplicate extension loading | Actual three-wiki install, scoped DB accounts, file-based passwords, extension dependency inventory and updater checks passed. |
| Reset removed shared source data or could proceed after failed shutdown | Runtime-owned path cleanup only; matching project and symlink checks; failed shutdown preserves state. Regression tests passed. |
| Cached exhausted histories skipped integrity/gap checks; orphan/support records could retain stale content hashes | Committed batch checksums, explicit orphan recovery, anchor checks and resumable gap analysis; corruption/recovery tests passed. Cached records are rehashed before recovery or import, including supporting revisions; positive and tamper-negative tests passed. Sol reproduced orphan tampering independently. |
| Source/local ID collisions or self-consistent forged mappings could pass | Independent expected inventories and source-wiki-scoped keys; exact source/local content and metadata joins; forgery/missing/changed-revision negatives passed. |
| XML was well formed but incompatible with native importer | Compared with pinned image dumpBackup. Direct revision model/format/text and base36 dump SHA-1 now import; C3 keeps original API hex SHA-1. Live 148-revision audit passed. |
| Import XML was absent from runtime mounts | Dedicated read-only imports subtree, not the entire secret-bearing runtime root. Native import passed. |
| Full acquisition opt-in was inverted/defaulted to sample | Explicit full manifest selection and opt-in guard; scope-aware 2 GiB sample / 50 GiB full disk floors; finite fake-source tests passed without full acquisition. |
| Managed config refresh and source footer were incorrect | Repeat setup refreshes only managed settings; generic source-project footer avoids fabricated per-title provenance. Credentials preserved; actual three-wiki HTML/route checks passed. |
| Offline verification could leave stale success | Bounded live Siteinfo/local API checks and fresh failure reports. Mocked offline/wrong-language/unexpected exceptions and Sol's real down/up control passed. |
| Initial local-edit probe compared submitted terminal newline | MediaWiki normalized save input. Corrected test snapshots the persisted result; exact revision/content stayed unchanged after reimport. |
| Browser harness assumed stale selectors, skipped handler readiness and treated composer text as saved | Inspected pinned DOM/client source. Sol directly reproduced the failures and a successful real reply. Wait for DiscussionTools initialization, full editor document-model text and composer teardown before reload. Use the actual reply-node API and a single accessible watch control. C and Sol each passed all three languages plus restart. One earlier Sol run timed out awaiting article VisualEditor model text; the successful workflow was reproduced without changing or bypassing the required saved-text assertions. No browser stability soak is claimed. |
| A browser tool waited for approval | Preserved A's worktree and transferred the bounded runtime snapshot to existing Luna B. B committed the completed handoff; no additional agent or approval bypass. |
| A worker-to-root message was rejected by automatic review | Root reads authorized compact thread snapshots instead; no retry through an unauthorized outbound channel. |

## Reproduction and evidence limits

Run the three deterministic suites documented in the README. `tests/infra/run_browser_acceptance.py` creates and removes only its own isolated project. The final Sol run at `0b3564b` completed with exit 0, including cleanup. Core runtime verification uses actual API Siteinfo; sample/full verification independently exposes their own scope.

Large artifacts and credentials remain outside Git. Useful external evidence includes `sol-independent-source-audit.json` under B reports, `sol-local-history-audit.json` in both integration/default roots, and the root's `/private/tmp/palimpsest-sol-*.json` and browser log. These paths document this local run; teammates reproduce with committed commands/fixtures rather than depending on ephemeral files.

Full T10 acquisition/import and rendering closure remain outstanding under approved D5. Linux/amd64 end-to-end Docker/browser behavior must be recorded on an actual Linux runner; architecture manifests and macOS ARM64 tests are not that evidence. No benchmark or full-history completeness is inferred from a six-page sample.

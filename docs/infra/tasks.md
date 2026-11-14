# Implementation and verification task plan

Status: D1–D6 approved on 2026-11-14. T00–T06 and T08–T09 accepted for infrastructure/sample scope. T07 framework/import adapter verified; real rendering dependency closure remains incomplete. T10 full history/import NOT RUN. T11 delivery branch is infra-set-up; no merge is authorized. See verification.md for exact tested revision, evidence and limits.
Requirement definitions: [spec.md](spec.md); architecture/contracts: [design.md](design.md).
Registry and repair protocol: [orchestration.md](orchestration.md).

## Dependency graph and ownership

| Task | Owner/files (proposed) | Requires | Requirements | Acceptance/evidence |
|---|---|---|---|---|
| T00 Approve scope/design | Owner + orchestrator; docs/infra/* | Phase 1 | R01–R14 | Explicit D1–D6 approval recorded; unresolved choices block affected work |
| T01 Freeze contracts and baseline | Orchestrator; docs/infra/*, scripts/wiki dispatcher contract, integration branch | T00 | R01,R12,R14 | Approved spec committed after permission gate; C1–C5 schemas/examples and fixed base SHA shared |
| T02 Verify pins/dependencies/platforms | A; infra/wiki/version lock, Dockerfiles, config | T01 | R01,R03,R13 | Exact multi-platform digests, extension dependency closure, build smoke; unsupported platform documented |
| T03 Runtime bootstrap/lifecycle | A; infra/wiki/compose*, config/, runtime/, extensions/, scripts/runtime* | T02 | R01–R03,R10,R11 | Three initialized health-checked wikis, jobs, local ports, persistence, no-op rerun and explicit reset tests |
| T04 Dataset lock/membership | B; infra/data/*, scripts/data*, dataset lock | T01 | R02,R04,R08 | Checksums, language counts and unique S keys; corruption/duplicate/schema negatives |
| T05 Anchor/history acquisition | B; same data-owned paths | T04 | R05–R08 | Real fi/sv/en anchor spike, complete continuation, failure queue, interrupt/resume evidence; measure M overlap only if using that optional shortcut |
| T06 XML/provenance/import adapter | B; data export/import modules | T05; C1 available for live integration | R05–R08,R12 | Historical metadata retained; source/local mapping reconciled; duplicate/retry/local-edit tests |
| T07 Rendering dependency import | B; data support modules | T05,T06; D3 | R03,R09 | Recursive support inventory, loop termination, missing support exceptions, sampled historical rendering |
| T08 Acceptance harness and CI | C; tests/infra/*, .github/workflows/infra.yml, docs/infra/quickstart.md | T01 for fixture work; T03/T06 for live checks | R01–R13 | Independent behavioral tests, failing fixtures detected, no full-corpus download in ordinary CI |
| T09 Integration and repairs | Orchestrator; integration branch, shared dispatcher, .gitignore, README.md, docs/infra/* | T03,T06–T08 | R01–R14 | Sol review of diffs plus fresh-project real smoke; send findings to original worker chats and rerun |
| T10 Full corpus run and audit | B executes, orchestrator verifies | T09 | R04–R09,R12 | All 29,460 expected S keys reconciled; all required histories accounted for; separate render report |
| T11 Delivery and PR | Orchestrator only; docs and PR | T09; D5 governs outstanding T10 | R13,R14 | Tested code revision recorded, concise file/reason table, actual coverage and blockers stated; no merge |

T02/T03 (A), T04–T07 (B), and initial fixture/CI work T08 (C) can overlap only after T01 contracts are fixed. Live T06/T08 waits for T03's reviewed runtime. B's dependent acquisition/export/support steps are sequential. C may implement tests from contracts while B builds producers, without changing those producers. T10 is not a hidden prerequisite of basic startup, and is not waived by T09.

Only orchestrator edits shared root files and the central four planning documents. Workers propose shared edits through handoff notes. Concrete path ownership and interfaces are frozen in contracts.md before worker launch.

## Behavioral verification contract

Tests assert durable state and API/browser observations. Logs, file presence and container exit alone do not establish outcome.

| Check | Req. | Procedure and observable success |
|---|---|---|
| V01 Fresh teammate setup | R01,R13 | Clean checkout/project/volumes; follow only quickstart; each language reports correct site language and DB-backed page retrieval |
| V02 Isolation | R02 | Same title and same source numeric IDs in two language fixtures; distinct mappings and independent edits |
| V03 Existing UI | R03 | In EACH wiki create account, login/logout, read/search known page, source-edit/save, visual-edit/save, view diff/history, post/reply talk, watch second-user edit |
| V04 Media/permissions | R03,R10 | Upload/display local image; online Commons separately; prohibited anonymous/admin action denied; no unrelated external write |
| V05 Dataset membership | R04,R08 | Locked release accepted; altered byte, duplicate source key, missing language and changed schema each cause failure |
| V06 Anchor truth | R05 | Real sample per language resolves declared source anchor and raw wikitext; unrelated/missing anchor fails without latest-content substitution |
| V07 Historical semantics | R05,R06 | Multi-revision fixture including same-second neighbors, minor edit, revert, Unicode and distinct authors; compare imported text, UTC times and author identity; local ID differs but mapping correct |
| V08 Continuation/retry | R05,R07 | Fake source has multiple batches, 429/backoff, transient 5xx, repeated token and exhausted retries; assert finite requests, correct inventory, explicit failure status |
| V09 Resume | R07 | Kill after durable batch and during import, resume; compare final source/local inventories with uninterrupted run |
| V10 Local edits/idempotence | R07,R10 | Import twice; counts unchanged; edit locally then rerun; local edit retained and no historical duplicate inserted |
| V11 Visibility and identity gaps | R05,R06,R12 | Suppressed text, missing parent, moved page/anchor mismatch and user/comment hidden fixtures; no fabricated content or silent success |
| V12 Rendering closure | R09 | Nested template → Lua/style plus dependency cycle; expected visible output or precise missing-dependency exception; supporting pages excluded from S counts |
| V13 Persistence | R10 | Create user/edit/upload, down/up and container recreation; compare durable state; data root preserved |
| V14 Extension mount/jobs | R11 | Isolated minimal verification extension loads; schema update runs; queued job completes in correct wiki with correct upload path |
| V15 False-green detector | R12 | Remove one required history and one mapping from controlled fixture; runtime still healthy but full report nonzero/failing with exact keys |
| V16 Full audit | R04–R09,R12 | Compare independent expected S set, acquired source inventory, local mapping/content hashes and counts; zero unresolved required records for full success |
| V17 Environment safety | R10,R13 | Two worker Compose projects coexist; teardown/reset touches only named project; secrets not tracked or printed; disk-floor checkpoint/resume exercised |
| V18 CI isolation | R13 | Deterministic fixture and integration jobs operate without full dataset; failure fixture causes failing job, successful fixture passes |
| V19 Reviewer trace | R14 | Sol High-or-stronger model and actual tested code revision recorded; worker evidence independently checked after integration |

Deterministic fixtures include ordinary multi-revision history, pagination/interruption, and missing/suppressed/invalid-source failure cases. Browser fixtures and tiny synthetic histories must be labeled synthetic. Real sample manifests must be explicit, selected deterministically from S, and include all three languages and at least two visible historical revisions per selected page. If a candidate lacks this, report why and choose another deterministically.

## Self-verifying loop and evidence

Each task: requirement check → worker implementation/tests → ready-for-review handoff → Sol diff/evidence review → reproduction → concrete finding → repair in same chat/worktree → affected retest. Integrate reviewed commits and repeat on combined environment. Never weaken the expected result to match implementation.

The orchestrator creates docs/infra/verification.md during implementation, containing code revision, platform/versions, actual models, commands, timestamps, evidence paths, per-requirement verdicts, findings/repairs/retests and remaining failures. Large output/screenshots/bulk data stay ignored; commit concise evidence summaries and fixture definitions.

A structural check only checks wiring/configuration; semantic review checks original source fidelity, workflow usability, durable state and honest completeness. These are separate from data completeness and cannot certify each other.

## Completion gates and reporting

T09 acceptance: all runtime/sample/negative/recovery checks pass on integrated code; unresolved substantive findings block infrastructure acceptance.
T10 acceptance: per-language expected/acquired/imported/reconciled source inventories and required histories match; all exceptions listed; full claim fails on unresolved required records.
D5 may permit an infrastructure PR with T10 explicitly outstanding, with resumable commands and measured progress. Do not mark T10 or full seeding complete.

Final PR: concrete behavior, files/reasons table, quickstart, exact verification model/revision, checks/results, coverage and blockers. Commit runtime, ingestion and verification changes by concern; preserve reviewed integration ancestry; no merge.

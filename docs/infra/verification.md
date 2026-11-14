# Verification record — in progress

Status: implementation and repair loop running; no infrastructure or full-corpus acceptance yet.
Orchestrator: gpt-6.1-sol, high reasoning, verified from session turn metadata. Three worker sessions verified gpt-6-luna/high. See orchestration.md for IDs/worktrees.

## Baseline and observed environment

- Approved specification baseline: e6d6e657ffe2a10bc7a598bc85f2ab1223741b7f.
- Shared dispatcher commit: a7b60bd; worker registry commit: 9228bd2.
- Final integrated tested code revision: NOT YET AVAILABLE. Work-in-progress worker files are not accepted commits.
- Host observed by orchestrator: Docker Desktop 4.63.0, engine 29.2.1, linux/arm64 server; Compose v5.0.2 observed earlier. Docker access requires authorized socket access outside this chat's shell sandbox.
- Repository PR target verified through GitHub CLI: Abhijay25/Palimpsest, base main, authenticated viewer has WRITE permission. No PR opened.
- Root launcher --help was exercised without Docker. Its independent routing tests are owned by worker C; root has not certified their results yet.

## Review findings and repair tracking

| ID | Owner | Finding | Repair / evidence status |
|---|---|---|---|
| F01 | Orchestrator | Flat project inventory was mistaken for enumeration of all source folders | User screenshot clarified Palimpsest is primary inside HackJunction. Three worker Git roots/remotes/baselines verified before implementation. Lesson recorded in originating workspace instructions. Resolved. |
| F02 | A | Initial stock settings used legacy Vector; job dependencies all pointed at Finnish wiki; health relied on escaped substring | Worker reports vector-2022, matching wiki dependencies and parsed JSON/language health checks repaired. Runtime acceptance pending integrated retest. |
| F03 | A | Extension inventory returned full release notes instead of version; duplicate registration/dependency checks needed | Repair requested; actual image inventory and live extension compatibility to be reviewed. |
| F04 | A | Installer confpath used filename where a directory is required; root installer credentials/script path needed checking | Repair requested with actual initialization test; pending handoff. |
| F05 | A | Reset recursively removed shared data root, which also holds datasets/histories | Requested runtime-owned deletion only, preserving unknown/source data; negative and persistence tests pending. |
| F06 | B | Cached completed histories bypassed integrity/anchor/gap checks; crash between batch and checkpoint could be mishandled | Requested authoritative batch checksums, explicit orphan recovery, crash/corruption fixtures and streaming. Worker repairing; not verified yet. |
| F07 | C | Independent oracle treated local IDs as globally unique across language DBs | Worker reports source-wiki-scoped identity and positive cross-language collision test. Orchestrator rerun pending. |
| F08 | C | Mutually consistent but wrong source/import records could pass an inventory-only oracle | Worker reports exact expected source comparisons, inline hash recalculation, full-count enforcement and stronger negatives. Orchestrator rerun pending. |
| F09 | A | Sandbox socket denial was described as unavailable Docker | Orchestrator executed escalated docker version successfully; worker resumed actual Docker setup. No host installation/start required. Resolved environment diagnosis. |
| F10 | Orchestrator | Some worker-to-orchestrator messages failed automatic authorization review | Workers instructed not to retry through alternate routes; orchestrator reads their results through authorized wait_threads snapshots. No implementation blocker. |

## Acceptance status

All V01–V19 remain pending final integrated verification. Worker-reported fixture passes are progress evidence, not overall acceptance.

| Scope | Current verdict |
|---|---|
| Runtime readiness | Not certified; A performing live setup |
| Independent deterministic fixtures | C reports passes; Sol rerun pending |
| Real multilingual anchor/history sample | B implementing; no result certified |
| Full S article membership locally verified/imported | Not yet performed/certified |
| Full required original history | Not acquired/reconciled; no completeness claim |
| Rendering dependency coverage | Pending implementation and sample verification |

No successful sample or container health result may change full-corpus verdict without an independent source/local inventory audit. Final evidence must record actual commands/results, code revision, platform and remaining failures before PR creation.

## Sol observations during integration (2026-11-14)

- Integrated C's reviewed test/CI commits as 130547d and 26a6d58.
- Ran `python3 -m unittest discover -s tests/infra -v` on integration commit 26a6d58: 14 passed, 1 explicitly Docker-gated test skipped. This includes positive and negative fixture/oracle and actual dispatcher routing checks; it does not exercise the not-yet-integrated runtime or data producers.
- Queried worker-A API endpoints on ports 18081,18082,18083 independently: languages fi/sv/en, MediaWiki 1.46.2 and databases mw_palimpsest-a_fi/sv/en matched. Worker-A code was still uncommitted; final integrated fresh-run verification remains required.
- Queried registry OCI image indexes for A's lock: MediaWiki sha256:13e538ae39045e78a7219269d036db3328f980f1a94ef1faabde075ba46eeb59 and MariaDB sha256:f16d7a344413e519dff518f27bdb221388f84b0d274c97c4fb5f2cb0dc1b34fa both declare linux/amd64 and linux/arm64. Metadata compatibility is not an amd64 runtime test.
- Read B's generated full corpus manifest: 29,460 unique source-wiki/page keys, counts fi=19,285, sv=4,921, en=5,254. This independently verifies manifest cardinality, not raw Parquet parsing or import completion.
- Independently queried source APIs using exact `revids` (no mixed pageids parameter) and recomputed UTF-8 SHA-1 for one sample anchor per language. Source page/revision IDs, S timestamp and wikitext model matched:

| Language | Source page | Anchor revision | UTC timestamp | Verified SHA-1 |
|---|---|---|---|---|
| fi | 1361114 | 20946650 | 2022-10-27T23:04:06Z | 46613b5763aa35ee2b57d2c99b5c6e7f0abea7ee |
| sv | 2814190 | 51437059 | 2022-11-03T09:24:47Z | 9b7a11d7d91dc7ac1caca3e668068a659ecb9f30 |
| en | 11610722 | 1272725070 | 2025-01-30T00:21:12Z | 270ef97ef973a376ddcee1d7b2a70fa8e1832f57 |

B separately reports a six-page/two-per-language probe with public predecessors. Full histories/imports remain unverified. No full-corpus completeness claim is made.

## Integrated checks at 0f6da8f (2026-11-14)

- Sol ran all three deterministic suites on the integrated code: 17 data, 7 runtime and 15 infrastructure tests passed; one opt-in Docker test skipped in that invocation. The skip does not certify Docker behavior.
- Fresh integrated Docker setup at 255556c completed for `palimpsest-integration`, data root `/private/tmp/palimpsest-integration-20261114`, ports 8081–8083. All three APIs reported ready. Sol created a per-language sentinel through authenticated APIs, ran repeated setup, down and up, then confirmed unchanged page IDs, revision IDs and content in each wiki. Evidence: external `sol-persistence-evidence.json`; generated credentials were not printed or committed.
- Sol used the existing PyArrow container with read-only asset/manifests mounts and an independent audit script: all 10 locked files matched exact lengths and SHA-256, and raw Parquet `(source wiki, page ID, anchor revision, title)` sets exactly matched the full C2 manifest. Counts fi=19,285, sv=4,921, en=5,254; 29,460 unique keys. This certifies membership, not histories/imports.
- Reviewed A's partial-setup repair and integrated as c04ddab. Successful language flags survive interrupted setup; mismatched settings/marker state fails safely. Seven runtime unit checks pass.
- Further Sol findings: missing read-only imports mount (A repair pending); C5 trusted same-size source/local mappings (B repair pending); explicit full acquisition guard was inverted and CLI selected sample under --all-pages (B repair pending). These prevent acceptance until repaired and retested.
- Real six-page history/import, actual browser workflows, extension mount/job and representative rendering checks remain pending. Full corpus history/import has not run.

# Blame verification record

Status: native attribution, dates, provenance, job/privacy controls, core workflows, persistence and a second isolated installation passed. Combined three-language keyboard/browser acceptance and final visual inspection also passed. Final CI/PR delivery is recorded in the PR. Full S import remains outside this feature.

Human scope update: defer Hostinger and full-corpus scale-up; deliver the local sample prototype first. No cloud resources were provisioned.

Actual orchestrator gpt-6.1-sol/high verified. Base15f713a; infrastructure PR1 open. Host macOS ARM64 with14GiB free at feature preflight; existing pinned images reused, no host package installs or full-history acquisition.

Executed preflight: verified actual Git root/remote, isolated feature branch and direct human fork authorization. Read-only current sample REST HTML200 and action=parse200; both omit data-parsoid, so arbitrary substring mapping rejected. Installed core1.46.2 paths discovered under includes/Parser and includes/Rest. The initial preflight did not count as feature acceptance.

This record separates historical failures, targeted repairs and subsequent verification. Never turn incomplete provenance or unsupported generated text into authoritative blame.

## Historical checkpoints

Pending statements in this section describe the checkpoint at that time; the final results section below supersedes them. Failures remain recorded to explain the repairs.

### Root T3 executed evidence

- Isolated project palimpsest-blame initialized on48081–48083 using existing pinned images. Parent8081–83 not modified.
- Copied only six completed C3 histories, checked committed batch hashes and compared source records before/after copy:148records. No DB/credentials/C4 copied.
- Native import into fresh feature DBs reconciled all148. Public sample verifier returned complete=true and no history/import failures; rendering remains separately incomplete.
- Provenance exporter203a102 verified C3 batches, C4 source/local joins and actual local API state before writing three canonical payload bundles. Counts fi2/62,sv2/12,en2/74. Explicit --install writes each bundle into that wiki's existing readonly config mount, avoiding Compose changes.
- Five root exporter tests passed with mocked transports: ordinary unrelated source/local IDs +Unicode/canonical hashes, corrupt batch, forged mapping, hidden source identity and local-state change between audit/export. No sockets or production state mutated.
- Actual worker session metadata verified Luna/high for A01a1d8b8-752c-7a03-bb06-fc30e1e74079,B01a1d8b8-8595-7523-99ef-999357bf8b18,C01a1d8b8-93f5-75f2-9b10-3fbd0b0d6cab before implementation.

Runtime/sample infrastructure success alone was not credited as a Blame pass.

### UI handoff and independent reproduction

B handoff94e76106b1b7a3d3d7eeb9f5b2d37d5de00efa08 integrated at34c3b27. Sol compared integrated resources/tests with the worker commit (no diff) and independently ran five Node helper cases plus two actual Chromium scripts in shared pinned image palimpsest-blame-browser:1.65.1 with --network none and only resources/tests mounted read-only. Passed DOM UTF-16/reverse/inline/unmapped/fragment-limit cases and mocked-transport action mounting, pinned snapshot, exact selection, filtered timeline, inline placement, UTC date query and guest-token job flow. These are real browser interaction tests with synthetic responses, not a native backend or real-job pass.

Findings returned to the same worker chats: quadratic whole-document LCS limit; missing multistep replacement ancestry; UI walker continue-loop hang; invalid minute normalization; absent article mount on custom action; undefined timeline selection variable; mutable-latest selection mismatch; guest-token rejection; backend timestamp/title/source-page/namespace mismatches; stale imported mapping yielding ready output; incomplete native-inline DSR support; generated-ancestor exclusion. First UI group repaired and reproduced as above. Backend fixes, native loading, job/resume and later focused UI repairs remain pending. No substantive gate has been waived.

### Combined integration checkpoint

- Native extension schema migration created both extension-owned job tables in all three isolated databases. Loader is feature-only; parent checkout/runtime remain unchanged.
- B repairs4653e22 and37391f1 integrated. Sol independently reran actual Chromium mouse partial drag, touch Inspect, pending initial revision pinning, mismatched-job rejection, exact status revision and anonymous CSRF mock flow: passed. Responses are mocked; this is not a native API pass.
- C8977fba integrated. Sol reproduced18 offline fixture/client checks; exporter5 checks also pass. Native ordinary API/action failed, so no downstream acceptance was credited.
- Sol reproduced installed compatibility failures through native maintenance eval: ParamValidator::PARAM_MIN undefined and Title::userCan removed. Review also found out-of-scope selection params, misspelled timestamp helper, silent200-revision truncation, missing durable-cache reuse, mismatched single-date bound field and query-style link normalization. Findings sent to the same A worker for repair. C harness repairs cover actual interpret/apply interactions, proper diff/contributions actions and missing-job semantics.

### Native results independently reproduced by Sol

- All six real imported pages passed `tests/blame/verify_provenance.py` against original C3 text/hash/metadata, C4 joins, exported and served bundles, and actual native API output: fi2pages/62revisions, sv2/12, en2/74. Tested after b6c9fec integration. Original source/local IDs are deliberately different.
- All18 native synthetic histories (six per language) and UTC boundary/order tests passed, including unchanged/multiple contributors, multistep replacements, deletion ancestry, repeated/moved/reverted ambiguity, noncomposable combining marks/emoji/Japanese and640-word sparse histories. Full `verify_live.py` then passed all three isolated local-edit invalidation probes without mutating shared history fixtures. Native large-fixture example:640words,5759source bytes,233985response bytes,49.24ms on one warm English request; not a throughput guarantee.
- `scripts/blame_verify_controls.py` passed four intended negative guards in each language: corrupt checksum, missing page in a valid bundle, forged revision hash inside a valid checksummed bundle, and missing bundle. Each began with a valid ordinary response, exposed no attribution/content on failure, and restored the exact served bytes. Original C3/C4 and export copies were untouched. Host bind-mounted fixture changes required observable container-byte confirmation; earlier invalid-JSON setup failures were not credited as checksum coverage.
- A real local edit on imported English Ulf Grönholm acquired local revision357 with no fabricated source provenance and correct new-token ownership. The source anchor remained unchanged. Article wording was restored by a subsequent real local edit; original imported revisions remain immutable.
- Native job construction initially failed because JobFactory supplies Title+params. After132aaa1, a clearly synthetic9-revision control processed3 revisions in one bounded run, persisted pending state, resumed after restarting only the English feature worker, and completed the pinned historical target's8 revisions. A public cached analysis/status both rejected newly hidden underlying content; visibility and service configuration were restored. The visibility test temporarily granted deleterevision only to the disposable English sysop, since the pinned default excludes that right. It did not change repository permissions or imported pages.
- The native205-revision Finnish job independently reached ready with processed=total=205. Its harness stopped on a missing top-level ready revision_id; that response-contract repair and public running-state normalization remain pending acceptance. No three-language long-job pass is claimed yet.
- Existing core browser regression passed in fi/sv/en with the extension enabled: account/login/logout, read/search, source+VisualEditor save, history/diff, DiscussionTools post/reply, second-user watchlist edits, upload/display and anonymous permission boundary. Persisted browser state is private and retained for the upcoming down/up check.
- Actual native desktop and touch-emulated phrase activation passed without JS errors. The first batched visual inspection found missing title, disappearing date/recovery controls and Vector's default desktop-width mobile canvas. Title/control repairs and feature-only VectorResponsive=true are integrated; final combined mobile/layout confirmation remains pending. Native iOS/Android selection gestures are not covered by emulation.

## Bounded algorithm comparison and memory evidence

`scripts/blame_benchmark.php` compares a whole-document bounded LCS baseline with the selected edge-trimmed LCS plus unique-anchor fallback, checking independently expected changed/unchanged ownership. On pinned PHP8.3.36/macOS ARM64 Docker, one run measured199-token sparse edit: baseline4.128ms versus selected0.544ms;1799-token sparse edit: baseline refused3236401cells above250000, selected6.038ms; dispersed edits: selected9.476ms with902tokens explicitly ambiguous. Combined peak10MiB; timings include different tokenization work and are illustrative, not database benchmarks.

The real Seppo Rapo history needs558849 charged lineage references (46revisions,138789history bytes,1677final tokens), measured91.6ms/16MiB peak in an isolated read-only engine copy. The initial250000-reference ceiling correctly refused it. A measured1000000-reference ceiling plus same-owner/ancestry span coalescing preserves IDs and fits the real provenance gate. A separate synthetic100000-cumulative-token workload peaked128MiB before MediaWiki overhead, motivating a conservative per-revision token guard before allocation; the final 20,000-token per-revision guard rejects before allocation. Response ceiling stays2MiB, with fail-closed attribution when a budget is exceeded.

## Final integrated results

Final functional code is `4f7869c5d2051bbd6dd5db74d80cb19e8a15f2bf`; the delivery commit adds documentation only. CI is recorded by exact run/head in the stacked PR, so this file does not preclaim a future check. Ordinary offline producer results reproduced at `868a615` (later browser-only harness repairs retained the same producer): 24 pinned-PHP semantic cases; six bundled-Node consumer cases; actual Chromium UI flow and DOM range suites with mocked transports; 24 independent fixture/API-client tests; five provenance-exporter semantic tests. Existing runtime/data/infra checks also passed (57 tests, one additional opt-in Docker test skipped). No host dependencies were installed.

Native macOS ARM64 / Docker Desktop, MediaWiki 1.46.2 / PHP 8.3.36 / MariaDB 11.8.9:

- Source provenance passed all six real articles and 148 original revisions in fi/sv/en, including after restart. Five integrity negatives per language (15 total) passed with exact intended reasons and no content/attribution: corrupt checksum, missing page, forged mapped revision, explicitly incomplete history, and missing served bundle. Served bytes were confirmed inside the container and restored in finally; C3/C4 originals and exported copies were unchanged.
- All 18 synthetic histories, UTC semantics and isolated local-edit invalidation passed natively. A separate oracle uses the retained source bundle and original timestamps, rather than extension output, for 16 Finnish / nine Swedish / 57 English revisions: inclusive as-of, exclusive before, exact pagination without duplicates, before-earliest empty and bound-specific cursors. Fractional-second bounds are explicitly rejected; supported precision is whole seconds.
- All three 205-revision jobs reached ready with every seeded core revision ID and exact source SHA-256. Historical targets remained pinned after later edits. Native POST-only and anonymous CSRF rejection passed. A separate nine-revision control checkpointed three revisions, resumed to its pinned eight-revision target after queue-worker restart, and rejected warm cached analyze/status after underlying text was hidden; visibility and temporary disposable-admin configuration were restored.
- Existing core behavior passed in all three languages with Blame enabled: accounts/login/logout, read/search, source and VisualEditor saves, history/diff, talk posts/replies, second-user watchlists, uploads/display and anonymous permissions. Actual down/up preserved users, edits, history, discussion, watchlists and uploads. Provenance passed again afterward.
- A second fresh project on 49081–49083 independently initialized all three schemas/databases, produced local attribution and completed queued results. It was stopped with its evidence preserved, and the feature project was restored. Parent 8081–8083 and its source data were untouched.
- Native oversized content rejected with `revision-token-limit-exceeded`, no spans/content and buildable=false. Obsolete algorithm/schema jobs do not consume current-version concurrency slots. The current algorithm key is `lcs-anchor-v4`.

### Measured request timings

English Ulf Grönholm, local snapshot 358, 59 revisions, 2,121 current source bytes, 85,236 retained imported-history bytes, 189 compact spans. Process-cold means the first request after restarting only its wiki container; the DB and persistent parser/derived caches remained warm. This is not disk-cold throughput. Small synchronous attribution recomputes the engine; warm does not imply derived-cache reuse.

| Request | Process-cold | Three warm repeats | Wire JSON |
|---|---:|---|---:|
| Attribution | 772.70 ms | 218.29 / 242.67 / 253.35 ms | 478,809 bytes |
| Date query | 429.20 ms | 31.34 / 23.36 / 20.37 ms | 828 bytes |

These are bounded samples on one machine, not capacity forecasts. The algorithm comparison and measured lineage/allocation budgets above justify explicit prototype limits; no system-versioned core tables were introduced.

### Evidence and limits

Private logs and state are retained under `/private/tmp/palimpsest-blame-*`, outside Git: native-api/jobs logs; controls-final JSON; job-controls JSON; date-oracle JSON; performance JSON; core-regression run/persistence logs; second-evidence JSON; and final offline logs. Earlier mixed-generated-selection failure evidence remains under the evidence/failures directory. No credentials, cookies, generated DBs or bulk corpus are committed.

Full S (29,460 articles), Hostinger, complete template/module/style dependency closure, exact historical rendering, live Wikipedia parity, physical iOS/Android selection, general throughput, and fresh Linux live-application/browser execution remain separate. Ordinary Linux CI exercises pinned PHP and mocked-transport Chromium, not a running MediaWiki stack. Imported identity mappings are operator-trusted checksummed records, not source-account authentication. Ambiguous lineage and generated text remain explicitly unavailable/uncertain; whole selections containing unverified visible words cannot produce partial authoritative histories.

The final native browser loop also distinguished harness readiness failures from a producer failure: root visibility was insufficient before asynchronous article loading; the keyboard loop initially mistook BODY text for the focused Blame link. Those harnesses were repaired without loosening selection/keyboard assertions. The resulting actual keyboard test then exposed the missing Escape close/focus-return path; the repaired shared close path then passed real Tab+Enter/Space, Escape and phrase focus return, including a replaced-node consumer fixture, before browser acceptance.

Functional, standards and security verdicts remain separate. Native functional checks and pinned-framework integration do not certify general WCAG compliance or Wikipedia-wide extension compatibility. Security evidence covers actual API POST/CSRF, core read permissions, hidden-text cache refusal and provenance corruption controls, plus isolated hidden-metadata/escaping fixtures; it is not a comprehensive security audit.

### Final browser and visual acceptance

At the final functional code SHA above, `browser_acceptance.py` passed all 21 language/viewport interaction groups: fi/sv/en desktop, touch-sized Inspect, exact mixed-contributor/Unicode/multistep history, generated and over-64-range refusal, exact cross-paragraph quote/end-block placement, real mouse partial-word offsets 13..16, comparison/contributions/internal-link/citation navigation, UTC interpretation/application/recovery, Tab navigation, Enter/Space, Escape/focus return, and old-DOM snapshot pinning across a real subsequent edit. No page JavaScript errors were observed. The root reproduced the affected Chromium consumer suite after the final interface repair.

Final English desktop/mobile captures were visually inspected in one batch: title and native tabs visible, exact quote/history inline beneath the statement, persistent recovery/date controls, readable wrapping, and a true 390px mobile viewport without horizontal overflow. Native device gestures and a full accessibility audit remain unverified. One Impeccable detector invocation returned no findings for the changed UI targets; this is a structural aid, not semantic acceptance. Existing remote footer/media asset availability is not certified. Screenshots and the final native log remain under `/private/tmp/palimpsest-blame-final-visual` and `/private/tmp/palimpsest-blame-native-browser-final.log`.

All worker-owned tracked files matched their final handoffs (A `c9089dc`, B `bfbbb0c`, C `b8c3cc4`). Temporary browser-origin/debug settings were removed and the exact repository runtime settings restored before the final localhost handoff. No parent service, source history or shared branch was reset.

Final localhost check after restoring settings: Finnish Seppo Rapo (revision49/451spans), Swedish Patis kyrka (revision10/466spans) and English Ulf Grönholm (revision358/189spans) all returned HTTP200, ready analysis and the current ResourceLoader script. No browser-container hostnames remained in API responses. The feature project remains running on48081–48083.

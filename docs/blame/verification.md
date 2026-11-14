# Blame verification record

Status: specification/contracts frozen; implementation not yet accepted. Full S import remains outside this feature.

Actual orchestrator gpt-6.1-sol/high verified. Base15f713a; infrastructure PR1 open. Host macOS ARM64 with14GiB free at feature preflight; existing pinned images reused, no host package installs or full-history acquisition.

Executed preflight: verified actual Git root/remote, isolated feature branch and direct human fork authorization. Read-only current sample REST HTML200 and action=parse200; both omit data-parsoid, so arbitrary substring mapping rejected. Installed core1.46.2 paths discovered under includes/Parser and includes/Rest. No feature tests have passed yet.

Record each worker's real SHA/models/tests, Sol findings/repairs/retests, real sample source/local audit, deliberate failure controls, desktop/mobile visual captures, performance measurements and final CI here. G1–G7 all pending. Never turn incomplete provenance or unsupported generated text into authoritative blame.

## Root T3 executed evidence

- Isolated project palimpsest-blame initialized on48081–48083 using existing pinned images. Parent8081–83 not modified.
- Copied only six completed C3 histories, checked committed batch hashes and compared source records before/after copy:148records. No DB/credentials/C4 copied.
- Native import into fresh feature DBs reconciled all148. Public sample verifier returned complete=true and no history/import failures; rendering remains separately incomplete.
- Provenance exporter203a102 verified C3 batches, C4 source/local joins and actual local API state before writing three canonical payload bundles. Counts fi2/62,sv2/12,en2/74. Explicit --install writes each bundle into that wiki's existing readonly config mount, avoiding Compose changes.
- Five root exporter tests passed with mocked transports: ordinary unrelated source/local IDs +Unicode/canonical hashes, corrupt batch, forged mapping, hidden source identity and local-state change between audit/export. No sockets or production state mutated.
- Actual worker session metadata verified Luna/high for A01a1d8b8-752c-7a03-bb06-fc30e1e74079,B01a1d8b8-8595-7523-99ef-999357bf8b18,C01a1d8b8-93f5-75f2-9b10-3fbd0b0d6cab before implementation.

Feature API/UI and G1–G7 remain pending integration. Runtime/sample infrastructure success is not a Blame pass.

## UI handoff and independent reproduction

B handoff94e76106b1b7a3d3d7eeb9f5b2d37d5de00efa08 integrated at34c3b27. Sol compared integrated resources/tests with the worker commit (no diff) and independently ran five Node helper cases plus two actual Chromium scripts in shared pinned image palimpsest-blame-browser:1.65.1 with --network none and only resources/tests mounted read-only. Passed DOM UTF-16/reverse/inline/unmapped/fragment-limit cases and mocked-transport action mounting, pinned snapshot, exact selection, filtered timeline, inline placement, UTC date query and guest-token job flow. These are real browser interaction tests with synthetic responses, not a native backend or real-job pass.

Findings returned to the same worker chats: quadratic whole-document LCS limit; missing multistep replacement ancestry; UI walker continue-loop hang; invalid minute normalization; absent article mount on custom action; undefined timeline selection variable; mutable-latest selection mismatch; guest-token rejection; backend timestamp/title/source-page/namespace mismatches; stale imported mapping yielding ready output; incomplete native-inline DSR support; generated-ancestor exclusion. First UI group repaired and reproduced as above. Backend fixes, native loading, job/resume and later focused UI repairs remain pending. No substantive gate has been waived.

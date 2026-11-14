# Infrastructure design — approved proposal

Related requirements: [spec.md](spec.md). Tasks: [tasks.md](tasks.md).
This is a design, not an implemented stack. No current runtime verification is claimed.

## Architecture and version choice

Three MediaWiki web containers share one application image and a MariaDB server, with independent databases, users/configuration, uploads and source-to-local maps for fi, sv, en. Proposed URLs are localhost:8081, :8082 and :8083 (configurable, bind 127.0.0.1). Each database gets a distinct restricted runtime account; installer credentials are scoped to initialization. Dedicated job processing uses the correct language configuration and uploads for each job. A job runner must not run before initialization or duplicate another worker's test jobs.

A one-shot tooling container downloads/validates S, reads Parquet, acquires original histories, produces XML, imports and reconciles. An extension mount is shared read-only by default; editing occurs in the host checkout. No upstream core fork and no Blame code.

| Component | Proposed pin | Verification/remaining gate |
|---|---|---|
| MediaWiki Apache image | mediawiki:1.46.2 | Docker Official Images manifest declares amd64 and arm64 support; resolve multi-platform digest after approval |
| MariaDB | mariadb:11.8.9 | Manifest declares amd64/arm64; pin multi-platform digest after approval and exercise MediaWiki compatibility |
| Vector + bundled extensions | Matching 1.46.2 release bundle | Record actual extension versions and dependencies from image after approval; do not mix master extensions |
| Python tooling | python:3.12.12-slim-bookworm candidate | Resolve architecture support and image digest before build |
| Parquet reader | pyarrow==22.0.0 candidate | Validate on target architectures, lock wheel/dependency hashes; no host installation |
| Browser verification | Version-locked browser automation tooling selected in T02 | Lock browser image/dependencies with test runner, no floating latest |

Version sources inspected on 2026-11-14:
- [MediaWiki image manifest](https://github.com/docker-library/official-images/blob/master/library/mediawiki), observed blob 21a63abbcc67be93537085770a7e4a57677655e6.
- [MariaDB image manifest](https://github.com/docker-library/official-images/blob/master/library/mariadb), observed blob 25e8138472e37690d5b434e9b1d03be8aad544a2.
- [MediaWiki image build source, fixed revision](https://github.com/wikimedia/mediawiki-docker/blob/4e224a65eb00cbe762f6635c5fd72509657fc019/1.46/apache/Dockerfile): PHP 8.3 Apache, mysqli, intl, APCu and LuaSandbox; downloads signed release bundle. Docker Official Image is not a claim of a Wikimedia production deployment.
- [Wiki family](https://www.mediawiki.org/wiki/Manual:Wiki_family) supports multiple wikis sharing an installation.

No image digests are invented here. T02 must resolve and commit them before executable setup is accepted. Incompatible candidates return as explicit design changes.

## Runtime and state

Proposed tracked layout: `infra/wiki/compose.yaml`, `infra/wiki/config/`, `infra/wiki/runtime/`, `infra/wiki/tooling/`, `infra/wiki/extensions/`, `scripts/wiki`, `tests/infra/`, `.github/workflows/infra.yml`, and these documents.

Generated state: ignored local environment/secrets, per-project named database/config/upload volumes, ignored dataset/history/checkpoint/output directories. A configured data root supports large external disks; container paths remain consistent. Do not store databases in the Git worktree.

Use an explicit Compose project name for every environment. Record port allocation and dataset root. Setup checks prerequisites, architecture, available ports and available disk; fails before mutating if invalid. Generate per-local-install secrets, never log passwords or commit generated settings. Initializer creates schemas/extensions once, then uses a schema-version marker; marker+DB inconsistency is an error, not a reason to wipe/reinstall.

Health requires initialized application API and database connectivity, rather than a successful Apache TCP connection. CLI status independently reports jobs and dataset stages. Resource limits and health timeouts are configurable. Shutdown preserves all volumes; reset names exactly the environment to delete and requires explicit confirmation. No global prune.

Core/bundled baseline includes Vector, VisualEditor, WikiEditor, Cite, ParserFunctions, Scribunto, TemplateData, TemplateStyles, Linter, DiscussionTools and Echo; consider PageImages/TextExtracts only if required by approved acceptance. Validate dependency closure before enabling. [DiscussionTools](https://www.mediawiki.org/wiki/Extension:DiscussionTools) depends on VisualEditor and Linter; Echo adds subscriptions. [VisualEditor](https://www.mediawiki.org/wiki/Extension:VisualEditor) integration needs actual UI save tests. [CirrusSearch](https://www.mediawiki.org/wiki/Extension:CirrusSearch) would add a separate search-service compatibility task; it is not silently provided by MariaDB.

## Command and file contracts

Proposed command interface (not available yet):
- `scripts/wiki setup`: prerequisite checks, image build/pull, database and empty wikis initialization, jobs startup.
- `scripts/wiki up|down|status|logs`: lifecycle/status; down retains data.
- `scripts/wiki dataset fetch`: locked S assets, optional locked M inputs.
- `scripts/wiki history acquire [--language fi|sv|en] [--sample-manifest PATH]`: resume source acquisition.
- `scripts/wiki data import [--sample-manifest PATH]`: import only acquired/validated records.
- `scripts/wiki verify --scope runtime|sample|full`: evidence/report and machine exit code.
- `scripts/wiki update`: supported schema/extension update; version mismatch fails clearly.
- `scripts/wiki reset --project NAME`: explicit destructive local environment deletion.

All commands accept a common environment/project and data-root configuration. Full mode never silently switches to a sample. Scope/sample identity is embedded in every output.

Interface C1 — runtime: environment manifest gives language → local API URL, service, database identity, image versions and project name; no credentials in published evidence.
C2 — corpus: release/tag/checksum identity, schema version and sorted unique `(source_wiki, source_page_id, anchor_revision_id)` records, title, timestamp, Wikidata ID, URL.
C3 — history: immutable source records keyed by `(source_wiki, source_revision_id)`, source page/parent IDs, UTC timestamp, visibility, author kind/value, comment, flags, model/format, raw content/hash, acquisition method and cutoff.
C4 — import: source revision → local page/revision mapping, batch/source checksum, imported/skipped/error status; supporting pages labeled separately.
C5 — report: schema version, tested code revision, scope, per-language expected/acquired/imported/reconciled counts, visibility/gap exceptions, rendering dependencies, failure list, command and exit status.

C1–C5 are versioned JSON manifests; bulk history may use compressed streams plus an indexed durable store. Select exact store after memory/throughput spike; no requirement to build a new application backend. Consumers fail on unsupported schema versions. Worker A owns C1 producer, B owns C2–C4 producers, C owns independent C1–C5 acceptance consumers. Orchestrator freezes example schemas before parallel edits.

## Dataset integrity and history pipeline

1. Lock S release asset names/URLs/lengths/SHA-256, including text, vectors and Finnish category files. Download atomically with validated resume, verify before parsing. Keep raw release immutable. Preserve all vectors as assets without deploying vector search.
2. Derive S membership from actual Parquet, validate schema/counts/uniqueness. Do not enumerate live categories as a replacement. Cross-language source keys prevent collisions.
3. Resolve each snapshot anchor. A small real fi/sv/en sample tests whether FineWiki's aliased version is an actual source revision. Fail unresolved anchors into a persistent exception queue.
4. Use locked M only where source page/anchor overlap is validated; filter later histories. API fallback covers Finnish gaps and sv/en. Never assume matching titles establish identity.
5. Read original public history from public source APIs or approved dumps, recording source boundaries and retrieval timestamps. Follow continuation completely, persist each batch before advancing checkpoint, detect repeated tokens, retry transient errors finitely and respect server backoff. Default at most one in-flight request per source wiki with a conservative interval; tune only from documented service policy.
6. Validate anchor membership and exact cutoff; do not rely solely on API timestamp boundaries. Detect differing bodies for one source ID, missing parents, suppressed fields, truncated payloads and moved/merged/deleted pages. No inaccessible text is filled with empty strings or inferred content.
7. Export bounded, deterministic MediaWiki XML batches. Escape content and preserve original revision metadata. Import with supported maintenance tooling, isolate imported authors from local accounts, and retain the explicit source/local mapping. Do not insert fabricated revision rows directly into core tables.
8. Reconcile local data against full source revision inventory, including original text hashes/timestamps/attribution, not just latest revision count. Rebuild required links, recent changes, site statistics and search data through supported maintenance routines before acceptance.
9. Repeat-import checks must preserve new local edits as current and avoid duplicate historical revisions. File checkpoints alone cannot certify DB completion; validate mapping and imported records on resume.

The [Revisions API](https://www.mediawiki.org/wiki/API:Revisions) exposes visibility indicators and pagination; content responses have a 50-revision limit. Remote revision identity and local identity must remain distinct. Endpoint exhaustion is necessary but not sufficient for complete import.

[XML import documentation](https://www.mediawiki.org/wiki/Manual:Importing_XML_dumps) describes content import, not full site restoration: accounts/media/logs require separate handling. M and S have different snapshots and corpus sizes; no measured overlap is claimed.

## Supporting content and historical fidelity

Maintain separate `corpus` and `supporting` inventories. Discover transcluded templates/modules/styles recursively for source anchors, with cycle detection and namespace allowlists; do not fetch the entire linked article graph. Record support versions and unresolved items. Prefer support versions at/before the anchor timestamp where retrievable, while caching by source revision. Current dependency discovery alone cannot certify historical transclusion closure; retain this limitation and test representative historical renders.

Local article links within S resolve locally; out-of-corpus red links and remote references are reported rather than pulling unlimited content. Categories supplied by S are retained separately from categories derived from original wikitext, whose state can differ by snapshot. Language counterpart links use Wikidata ID where supplied, without requiring a Wikidata service.

InstantCommons is proposed for online Commons media, with local uploads persistent. Missing historical files, non-Commons assets, Wikidata-driven infobox values or incompatible templates remain explicit exceptions. Exact Wikipedia historical pixels are not implied by preservation of article source history. D3 must approve these boundaries.

## Resource envelope and risk

Verified declarations: complete S download approximately 156 MB; M approximately 315 MB compressed but 12.2 GB raw text across its entire published Finnish set. S raw text/embeddings are not a predictor of sv/en history volume.

Planning estimates, not benchmarks: Docker allocation 4 CPUs/8 GB RAM; reserve 10 GB for empty runtime/images and begin full-history work only with at least 50 GB available on the data disk. Neither number guarantees sufficient space. Stream data, bound memory and pause safely before a configurable disk floor. Measure sample bytes/revisions and extrapolate per language with safety margin; popular-page tails can invalidate averages.

Runtime estimate must be derived from observed request counts, rate limits and import throughput. Full processing may require many hours or days. No completion-time promise in Phase 1. Bulk-data traffic owner B coordinates all sources; other workers use fixtures.

## Readiness

D1–D6 recommendations were approved by the owner on 2026-11-14. Current orchestrator metadata confirms gpt-6.1-sol with high reasoning (turn 01a1d768-0dc8-7fd3-8e9d-0c6d54a8c7b1). Runtime, imports and anchors remain unverified. Approval permits implementation; it does not certify candidate versions or accept incomplete source coverage. See contracts.md for frozen task interfaces.


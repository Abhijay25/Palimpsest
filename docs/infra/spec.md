# Palimpsest infrastructure specification

Status: **APPROVED — recommended D1–D6 accepted by owner on 2026-11-14**. Prepared 2026-11-14 (Europe/Helsinki).
Approved requirements from Phase 1; executed results and remaining coverage are recorded separately in verification.md.

## Repository and authority

Target: /Users/zhenghaofang/Coding Playground/junction-2026/Palimpsest.
Inspected clean branch: `infra-set-up`; HEAD `17b73fc0c285f38a036160679d469cc49ace9b5d`.
Origin: `git@github.com:Abhijay25/Palimpsest.git`. Repository currently contains README.md only.
No AGENTS.md was found at the target or inspected ancestor directories. The user's pasted SDD prompt governs this assignment.

Deliver infrastructure and ingestion for an actual MediaWiki application. Do not copy the separate Wikipedia Blame frontend, implement attribution/AI features, or modify that prototype. Runtime code, downloads, containers, commits, pushes, PRs, and worker launches require completion of this specification approval gate.

## Source findings and limits

The [dataset documentation](https://github.com/MariaDB/mariadb-wikipedia-datasets#at-a-glance) declares:
- S: 19,285 Finnish + 4,921 Swedish + 5,254 English articles = 29,460 language-specific pages; Markdown snapshots and embeddings.
- M: historical Finnish wikitext for 19,742 pages, 862,076 versions; published decompressed text size 12.2 GB. This is not the measured overlap with S.
- S's snapshot is August 2025; M extends to October 2026. Counts and dates are source declarations, not local measurements.

The [S builder](https://github.com/MariaDB/mariadb-wikipedia-datasets/blob/main/dataset_s.py) aliases FineWiki's `version` to `rev_id`. This alone does not prove every value resolves to a Wikipedia revision. At Phase 1, no Parquet asset had been downloaded or inspected. The later verification record distinguishes the actual full membership audit and six-page anchor/history sample from unverified full histories, M/S overlap and rendering fidelity.

## Proposed scope and feature matrix

“All existing Wikipedia features” is a product aspiration requiring explicit scope agreement. The baseline below was approved through the owner’s acceptance of recommended D1–D6 on 2026-11-14. It does not assert exact Wikimedia deployment parity.

| Workflow | Proposed provider | Acceptance behavior | Boundary requiring approval |
|---|---|---|---|
| Read/navigation | Core + Vector 2022 | Open an imported page, sections and local in-corpus links | Out-of-corpus article links may remain red links |
| Search | Core database search | Find seeded titles and a known indexed phrase | Wikipedia-scale ranking, advanced search and CirrusSearch deferred unless D2 chooses them |
| Accounts/login | Core local accounts | Create user, login/logout, independent sessions | No CentralAuth/SSO federation or restored source user accounts |
| Source editing | Core + WikiEditor | Save changed wikitext and reopen it | Source snapshots remain separately retained |
| Visual editing | VisualEditor + bundled Parsoid integration | Open, edit, save and reread through browser UI | Compatibility must be tested, not inferred from extension presence |
| History/diffs | Core + original-history import | Browse historical revisions, compare two versions, preserve attribution/times | Only obtainable public history; local IDs differ from source IDs |
| Talk pages | Core + DiscussionTools, VisualEditor, Linter; Echo | Post and reply; persisted discussion visible on reload | Historical talk-page corpus is supporting data, not included in S membership |
| Watchlists/notifications | Core + Echo | Watch a page; second local user's edit appears in watcher workflow | No SMTP delivery or global notifications in proposed baseline |
| Media | Core uploads + InstantCommons | Upload a local image; display an accessible Commons image | Remote Commons remains online; not a full local media archive |
| References/templates/Lua | Cite, ParserFunctions, Scribunto, TemplateData, TemplateStyles | Representative citation, nested template and module render | Supporting-content closure and historical rendering limits in D3 |
| Permissions | Core | Anonymous/registered/admin behavior matches documented local configuration | Full Wikimedia moderation/anti-abuse extension fleet is not proposed |
| Language navigation | Three language wikis + provenance mapping/interwiki configuration | Same title/IDs across languages stay distinct; available counterpart links resolve | No automatic Wikidata deployment or translation product |

The owner approved the proposed D2/D3 boundaries on 2026-11-14. Additional Wikimedia features must be listed and estimated before any claim of full parity.

## Requirements and measurable acceptance

| ID | Requirement | Acceptance condition |
|---|---|---|
| R01 | Reproducible local runtime | Documented clean-clone commands initialize all three wikis without manual container configuration; versions and image digests recorded |
| R02 | Language and identity isolation | fi/sv/en remain distinct for equal titles and IDs; mapping uniquely keys source wiki + source ID |
| R03 | Existing wiki workflows | Every approved feature-matrix row passes a browser/API acceptance check in each language |
| R04 | Exact S membership | Verified release files yield exactly the expected unique per-language pages; duplicates/schema/count changes fail rather than silently change corpus |
| R05 | Original public history | Every S page has a validated snapshot anchor, exhausted public-history enumeration through the approved cutoff, retained wikitext/metadata, and reconciled local import; unresolved exceptions prevent full success |
| R06 | Provenance | Source page/revision/parent IDs, language, source URL, UTC time, public author/comment/minor flag, content hash, acquisition source and local ID mapping are retained where available; missing fields explicitly marked |
| R07 | Resume and idempotence | Interrupt and rerun acquisition/import; no lost completed records or duplicate revisions; local edits survive reruns |
| R08 | Integrity | Locked release assets pass SHA-256 before use; corrupt assets, conflicting source revisions and invalid XML fail with actionable status |
| R09 | Rendering support | Approved representative pages pass template/module/reference checks; supporting dependencies have separate inventory and unresolved-dependency report |
| R10 | Persistence and locality | Restart/shutdown preserves edits, users, images and state; HTTP ports bind localhost; normal shutdown cannot delete data |
| R11 | Extension integration | Documented development mount and schema-update workflow accepts a minimal isolated test extension without modifying upstream core; no product feature shipped |
| R12 | Honest coverage | Machine-readable reports and failing exit status expose missing membership/history/import/mapping; runtime/sample/full-corpus states are separate |
| R13 | Team setup and CI | Supported-platform quickstart, isolated fixture tests, negative/recovery tests and container smoke checks are documented and executable |
| R14 | Review and agent traceability | Sol High-or-stronger orchestrator verifies integrated changes and final code revision; worker chat/model/commit/test records are retained |

### Historical cutoff proposal (D1)

S is the membership and target snapshot authority. Obtain all publicly accessible original revisions from the earliest available revision through each S anchor, inclusively. Do not import later M/live revisions as the seed latest version. Keep raw S Markdown/vectors as immutable research assets, separate from MediaWiki's original wikitext.

Resolve an anchor by source wiki and revision ID, validate page ownership, timestamp and content model, and record title changes/merges as explicit cases. Never substitute a latest page when the anchor fails. The Revisions API's `rvendid` is a timestamp bound, so same-timestamp neighbors require explicit filtering to the validated source anchor and a regression case ([API documentation](https://www.mediawiki.org/wiki/API:Revisions)). Retain an exact source-ID membership list for each history.

After seeding, new local edits may advance the local page. Dataset embeddings then describe the original snapshot, not the edited page; retain this distinction in metadata without implementing search/AI features.

### Completeness definition

“Complete” means complete **obtainable public history under the approved policy**, not access to suppressed/deleted private content and not reconstruction of original site accounts or logs. Retrieval completion requires exhausted pagination, anchor presence, source inventory reconciliation and visibility/gap accounting. A parent-ID gap is an exception to investigate, not a fabricated parent or automatic proof of corruption.

If any required source content is unavailable, the default full-history gate fails and reports affected pages/revisions. Owner acceptance of explicit exceptions must be recorded separately; exceptions cannot be silently counted as complete. Supporting templates may change historical rendering even when article source history is complete.

Reports expose independent statuses:
1. Runtime ready.
2. Sample import verified.
3. Full S membership imported.
4. Required source histories acquired and reconciled.
5. Rendering dependency coverage.
A single green runtime check must never imply all five passed.

## Proposed operational boundaries

Host targets: macOS ARM64 and Linux amd64 with Docker Compose v2-compatible commands; other platforms require separate evidence. No host PHP, database or data-science installation. A small standard-library launcher may require Python 3.11+; approve this prerequisite in D4. All heavy tooling runs in containers.

Initial setup creates empty functional wikis. Full data acquisition/import is a separate explicit, resumable command. Downloads, source API reads, initial image pulls and Commons need internet; seeded local read/edit/history should remain usable offline except remote media.

No product features, production hosting, Wikimedia account credentials, automatic host-package installation, or global Docker cleanup. Generated secrets and bulk data stay outside Git. Attribution/source links and dataset license notices accompany retained content.

## Decisions for owner approval

| Decision | Recommended proposal | Consequence/alternative |
|---|---|---|
| D1 Snapshot/history cutoff | Public history through validated S anchor; exceptions fail full coverage | Importing latest history changes S alignment; define separately if desired |
| D2 Feature scope | Approve matrix baseline; core search, local accounts, no full Wikimedia fleet | If literal feature parity/CirrusSearch is required, expand design/tasks/resources before implementation |
| D3 Rendering/media | Import recursive supporting templates/modules/styles with recorded versions, fetch-time cutoffs and unresolved inventory; online Commons | Exact historical rendering or fully offline media requires additional datasets/services and validation |
| D4 Runtime/layout | Three local wikis, one MariaDB server, Docker + Python launcher; target macOS ARM64/Linux amd64 | One multilingual wiki changes namespace/identity semantics |
| D5 Long-run completion | Deliver independently verified infrastructure + sample, with full-corpus jobs/status separately reported | PR may be infrastructure-ready while full seed is outstanding; never claim full seed until reconciled |
| D6 Models/worker chats | One Sol High-or-stronger orchestrator, at most three visible Luna worker chats/worktrees | Verify actual model settings before implementation; no hidden subagents |

Approval recorded: the owner stated “proceed with the recommended proposal for D1-6, then continue with the next phase if there are no more clarifying questions.” All recommended choices are accepted, including D5’s separate full-corpus reporting. Phase 2 is authorized. Model configuration and the registered Palimpsest source root were verified. Three visible Luna worker chats/worktrees were created; actual identities and integration are recorded in orchestration.md.

## Evidence and resource uncertainty

[S release metadata](https://api.github.com/repos/MariaDB/mariadb-wikipedia-datasets/releases/tags/s-2026-10) was inspected read-only on 2026-11-14. Published counts and asset metadata are verified declarations; downloaded content and end-to-end behavior are not verified. See design.md for candidate versions, resource planning and sources.

# Palimpsest Library — three-hour implementation prompt

You are implementing a new, separate Library frontend for Palimpsest. Deliver a working local experience using Spec-Driven Development, actual MariaDB vector search, real imported Wikipedia histories, and the existing PalimpsestBlame backend.

Repository: `/Users/zhenghaofang/Coding Playground/junction-2026/Palimpsest`.

Read `PRODUCT.md` and this prompt as the confirmed product brief. Proceed with routine engineering decisions, implementation, testing, and repairs. Ask only about a required external dependency or consequential conflict that cannot be resolved from current source. Do not reopen the settled product choices below.

The earlier infrastructure prompt is a structural reference. Its infrastructure-only worker and external-action authorisations do not transfer to this feature. Use one implementation agent unless the human separately authorises delegation. Deliver a local reviewable change; pushing, opening a PR, publishing, or merging requires applicable authorisation in the implementation session.

## 1. Hard timebox

Start a wall-clock timer when execution of this prompt begins. The budget is **180 minutes total**, including preflight, concise specifications, dependency installation, acquisition/import, implementation, testing, repairs, and documentation. This prompt-writing conversation is outside that future execution timer.

Record start time, deadline, actual elapsed time, and milestone checks. Check remaining time at least every 15 minutes. Reserve the final 15 minutes for bounded verification, safe checkpointing, and handoff. Avoid starting new expensive work during that reserve.

At the deadline, stop implementation. Checkpoint or stop only jobs owned by this feature safely; preserve resumable source data and existing shared services. Report unfinished requirements accurately. Give the human a prioritised continuation list with dependencies, estimated additional effort and uncertainty, and the next concrete step. Continue beyond the cap only after explicit additional-time approval. Do not silently downgrade a required feature or label it complete.

This is an ambitious integration timebox. Treat complete delivery as an outcome to verify, not a promise that all dependencies fit three hours.

## 2. Confirmed experience

The primary goal is an impressive exploratory Wikipedia universe. History is secondary in the initial discovery experience and becomes a concrete spatial interaction after selecting a book.

The exact journey is:

**Semantic bookshelf lattice → topic-book and language → first-person revision corridor → selected edition → full book reader with inline Blame → return to the same corridor position.**

- The overall space resembles Interstellar: recognisable shelves and books extending above, below, and into the distance. Use the Library of Babel metaphor and Zoomquilt-inspired continuity.
- Navigation is guided scroll/zoom with clickable destinations and search. The history corridor uses an eye-height first-person camera. Walking forward travels from new to old; walking backward returns toward new. A visible character/avatar is unnecessary.
- One topic-book groups Finnish, Swedish, and English articles about the same entity. Use verified Wikidata identity, preserving distinct language-specific article identities underneath. Never group articles merely because their titles match.
- Every admitted topic-book must offer all three languages, each with real imported history. A smaller collection is acceptable.
- Each history corridor belongs to **one selected topic-book and one selected language**.
- Each revision occurs once in that corridor: newest on the left, next on the right, alternating deeper toward older editions. Use a bounded rendered window and load/recycle geometry while preserving the complete reachable revision sequence. All imported editions must be reachable.
- Use revision order for predictable physical spacing and show actual UTC dates/revision labels. Equal shelf spacing must not imply equal elapsed time.
- Clicking an edition pauses camera movement and opens a large book-styled HTML overlay. It contains the full selectable article and passage-level Blame, expanding directly beneath the selected statement/block. A link-only Blame handoff does not satisfy this requirement.
- While reading, scroll operates on the article and selection operates on its text. Scene motion stays paused. Closing the reader restores camera position/orientation, selected edition, and sensible keyboard focus. Escape closes an inline inspection before closing the reader.
- Switching language opens the **latest imported edition in that language**, explicitly announces the date change, clears stale selection/analysis, and resets that language's corridor to its newest end. Keep the reader open if the switch occurred inside it. Histories and revision numbers are independent across languages.
- Provide an ordinary **Open in Palimpsest** action for the selected local revision, plus a verified **View original Wikipedia revision** action where provenance supports it. An optional live-page link must be labelled as live/current.

The environment can convey vastness over a finite collection. Display the actual curated topic/article counts. Ambient architectural repetition must not fabricate selectable article titles or histories. Generated answers with citations are future work.

## 3. Preflight and ownership

Read applicable AGENTS.md files, current Git state, worktrees, remotes, README, `docs/infra/{spec,design,contracts,verification}.md`, and the current Blame spec/contracts/verification/revision-colour requirements before editing.

Important source routes, to verify afresh:

- The main checkout was last inspected on `feature/blame-sdd`, containing the Blame implementation brief but not the integrated extension.
- The actual extension was found in `/Users/zhenghaofang/.codex/worktrees/palimpsest-blame/Palimpsest`, branch `feature/blame-implementation`. The last observed head during prompt preparation was `b0b712adbe9255d5104dcf6198befaf998ca5cb8`, with ongoing uncommitted documentation changes. This is a discovery pointer, not a frozen or certified implementation base.
- Current extension paths there: `infra/wiki/extensions/PalimpsestBlame/`, `docs/blame/contracts.md`, `docs/blame/revision-colours.md`, and `docs/blame/verification.md`.
- The Blame feature runtime was documented on localhost ports 48081–48083; infrastructure defaults use 8081–8083. Verify actual ownership, data roots, versions and readiness. Do not reuse ports or mutate runtimes based only on this note.
- `/Users/zhenghaofang/Documents/ChatGPT/HackJunction` is the separate fictional Blame prototype and a read-only UX reference. Preserve its files and running service, including its frontend port.

Choose a current, coherent Blame-integrated baseline and record the SHA. Establish an isolated feature branch/worktree when available; preserve all unrelated edits. Do not checkout/reset another active worktree or transplant its uncommitted files silently. Resolve source/contract drift before depending on fields.

Keep the new app in a clearly owned directory such as `apps/library/`; the exact location is delegated. Prefer React/TypeScript + Three.js with a small backend, adjusting details based on source evidence. Choose free localhost-only ports and isolated generated-data paths. Reuse the pinned compatible MariaDB/runtime where safe, or use an explicitly isolated runtime. Keep database access behind the backend and generated credentials outside Git.

During the first bounded preflight, verify an actual Blame response for an exact imported revision, access to the locked S assets, a viable trilingual curation/import path, MariaDB native vector capability, and Ollama/bge-m3 availability. Record any material blocker immediately while completing independent work within the cap.

## 4. Concise SDD package

Before dependent edits, write a compact `docs/library/spec.md`, `design.md`, and `tasks.md`. Capture requirement IDs, chosen baseline, corpus, API adapters, identity/state transitions, ownership, dependencies, and acceptance checks. Reuse existing infra/Blame contracts instead of recreating their engines.

Maintain `verification.md` with commands, observed results, tested revisions and limits. At handoff write `future-work.md`, separating unfinished required work from optional extensions. Routine repairs within this brief need no new approval.

## 5. Real data and semantic discovery

### Curated collection

Recommended sizing default: **three distinct topic-books, nine language articles**, growing toward three to five topic-books if time permits. Choose a coherent set with genuine semantic relationships, manageable public histories, and useful attributable passages. This numerical recommendation is an implementation default derived from the timebox. Freeze the selected manifest and acceptance sample before evaluating results.

The local S manifest was observed to contain 29,460 language articles and 2,919 Wikidata groups with all three snapshot languages. The existing six-page imported fixture has no fully trilingual group. Snapshot presence does not establish history readiness. Do not present that fixture alone as meeting the trilingual requirement.

Use S membership and validated source revision anchors. Acquire/import original publicly available histories through each language article's declared anchor using the existing resumable pipeline. Validate provenance bundles, separate source/local identifiers, and readiness for Blame. Missing/hidden data and incomplete histories must retain their actual scope. A topic with a missing language/history cannot count as an admitted trilingual topic-book.

Preserve original wikitext and supported rendering; do not represent converted Markdown as original historical text. Retain full article content in the reader while preserving existing attribution limitations for templates/generated text. Use supported imports, original attribution and public visibility. Do not modify MediaWiki core tables, source datasets, unrelated local edits, or another feature's provenance bundles. Feature-owned new imports/bundles must have explicit runtime ownership and resumable manifests.

Define “latest imported” from the selected imported source scope and its mappings. A later local edit or the live Wikipedia page is a different state. Pin the exact local revision when opening the initial book or switching language; do not rely on an API default of latest local revision.

### Embeddings and MariaDB

The approved mechanism is: load article metadata/vectors into MariaDB; use multilingual bge-m3 embeddings to find related subjects; embed text queries with the compatible model through Ollama; retrieve relevant topics across languages.

- Prefer validated S precomputed bge-m3 article vectors for their exact source snapshots. Generate new article vectors only when needed, with compatible model/preprocessing and recorded revision identity. Record model, dimensions, source/cutoff, and available model-version/digest information; disclose unknown metadata.
- S supplies 1024-dimensional bge-m3 vectors, including truncation metadata. Respect its generation configuration and keep query embeddings compatible. Full reading must not be truncated to the embedding input.
- Use actual native MariaDB VECTOR storage/index/query operations. Validate dimensions and distance configuration. A live similarity query must power related-book results; frontend hardcoded relationships are not sufficient.
- Group multilingual hits by verified topic identity and retain the matched article/language. Search targets the admitted collection for this build. Handle an unavailable model/query service explicitly.
- Derive a stable, deterministic spatial layout from actual vector relationships. A precomputed layout cache is fine if its provenance and invalidation are defined. Small-corpus projection/placement is delegated; choose a simple inspectable method. Approximate spatial distance must not be presented as an exact semantic measurement.
- Keep the overview anchored while visitors inspect historical editions. No per-revision embeddings or historical semantic drift are required initially.
- Semantic discovery and chronology have distinct axes. Revision colour means last text change, not similarity, editor identity, truth, or reliability.

Relevant primary references: [MariaDB vector overview](https://mariadb.com/docs/server/reference/sql-structure/vectors/vector-overview), [dataset schema/model/cutoffs](https://github.com/MariaDB/mariadb-wikipedia-datasets#at-a-glance). Recheck installed versions and source generation code for consequential details.

## 6. Existing Blame integration

Inspect the current producer and consumer together. The documented API was `action=palimpsestblame`, `formatversion=2`, with `op=analyze|versions|build|status`, a title, and an exact **local** revision ID. The actual current contract takes precedence after validation.

Ready analysis documents annotated parsed HTML, source offsets/spans, revision/event metadata, provenance/coverage and ambiguity. Source ranges use zero-based UTF-16 offsets, end exclusive. Preserve `data-pb-*` mapping metadata through safe HTML rendering. Never match arbitrary visible text back to wikitext using the first substring occurrence.

The native UI depends on MediaWiki globals and its DOM. It is not a drop-in standalone React component. Reuse supported API output, shared pure helpers and proven semantics, adding a small scoped adapter/reader rather than assuming the native entry script mounts outside MediaWiki.

Requirements:

- Article HTML, exact selection, selected edition, analysis and timeline always share language/page/revision identity. Cancel or ignore stale responses after navigation, language changes, and closing.
- Selecting a word/phrase or a cross-contributor passage retains the exact visible quote. Show each intersecting contribution and relevant introductions/replacements/deletions beneath the selected statement or last selected block. Keep unrelated edits outside the selected-word timeline.
- Colour identifies the last-changing revision. Preserve matching categorical colours and labelled swatches across article, retained quote, revision groups and timeline, including phrase focus. Expose public editor/date/revision details; attribution is not proof of a claim.
- Respect existing whole-selection refusal for generated/unmapped portions and configured fragment limits. Preserve ambiguity on moves, duplicate wording, reverts and unavailable parents. Do not invent ownership or weaken existing oracles.
- Use the actual predecessor for comparisons. Derive source links from verified source/local mappings, never numeric ID equality. Keep hidden identities/comments/content unavailable.
- Preserve pending/build/status semantics, exact job targets, bounded polling and real CSRF/session requirements if analysis preparation needs a write. Never use privileged service credentials to turn the public reader into a permission bypass.
- If a backend proxy is needed, allowlist configured wiki endpoints and preserve public read/visibility checks. Avoid arbitrary URL fetching, unsafe HTML execution, stale private-content caching, exposed secrets and permissive cross-origin configuration.

MariaDB system-versioned tables are not required for this feature. Existing revision records and the Blame API provide the chronology/attribution. Database system time is distinct from original Wikipedia edit time; see [MariaDB temporal semantics](https://mariadb.com/docs/server/reference/sql-structure/temporal-tables/system-versioned-tables).

## 7. Scene, reader and state contract

Record explicit states for overview, search/loading/results/empty/error, corridor preparation/walking, edition focus, reader loading/ready/unavailable, inline selection, language change and recovery.

Use stable topic/language/page/revision keys and a bookmarkable route or equivalent deterministic state. Store camera position and orientation separately from reader selection. Back/close must not silently jump to another edition. Missing deep-linked content produces an explicit state, not a fallback latest revision.

Render a bounded number of shelf/edition meshes and labels. Keep the logical newest-to-oldest list complete, stably ordered through same-second revisions and paginated boundaries. Verify every imported revision occurs exactly once. Keep the entrance/newest/older direction legible and supply an accessible return-to-newest action.

Use tangible shelf geometry, deep perspective, atmospheric lighting and restrained transitions consistent with the pinned references. Keep book text as readable selectable HTML. Scope styles to the new app; preserve article links, headings, citations and source distinctions. Avoid expensive decorative assets or simulated book mechanics that block the core journey.

Provide keyboard-accessible destinations, corridor movement, edition activation, reader controls and focus return. Reduced motion and missing WebGL use a functional topic/revision list with the same reader and inline Blame. Mobile may use this fallback. Handle WebGL context loss and service failures usefully.

Measure an actual fixed walking sequence on the stated desktop environment. Target at least 30 FPS with bounded active geometry; report measured results and limitations. A passing build or static screenshot does not establish interaction performance.

## 8. Requirements and verification

Maintain a requirement-to-evidence table. At minimum:

| ID | Required outcome | Observable acceptance |
|---|---|---|
| L01 | Separate reproducible localhost app | Documented clean start; original prototype/wiki services remain usable |
| L02 | Small real trilingual collection | At least three admitted topic-books by the recommended sizing default; fi/sv/en original histories and provenance verified for each |
| L03 | Genuine MariaDB/Ollama discovery | Actual compatible query embedding, native vector result and relevant cross-language topic navigation; actual model/database failures produce errors |
| L04 | Spatial topic discovery | Guided lattice navigation, visible real topic identities, stable vector-derived relationships, correct search destination |
| L05 | First-person history corridor | One topic/language; forward new-to-old; unique alternating left/right revisions; all imported editions reachable across window boundaries |
| L06 | Full book reader | Clicking an edition pauses movement and opens full content for that exact revision; selection/reader scrolling do not move the camera |
| L07 | Real inline Blame | Exact native partial/cross-contributor selection; matching revision colours/groups; relevant replacement/deletion history beneath the selected block |
| L08 | Honest unsupported states | Generated/hidden/missing/stale/ambiguous/over-limit cases retain existing guard behaviour and expose no fabricated attribution |
| L09 | Language reset | Switching language opens latest imported target, announces actual new date, clears old quote/analysis, and resets corridor appropriately |
| L10 | Return/navigation identity | Closing restores corridor position/orientation/focus; deep links, ordinary wiki and original-source actions target verified identities |
| L11 | Usable fallback/performance | Keyboard and reduced-motion/non-WebGL route reach the same reader; narrow viewport is usable; actual walking performance measured |
| L12 | Timebox/evidence | Elapsed time, tested SHA/runtime, commands, coverage, failed/unverified criteria, startup URL and continuation list reported accurately |

Freeze focused acceptance inputs before evaluating the implementation. Use isolated synthetic fixtures for deterministic negatives, clearly distinguished from real articles. Include colliding numeric IDs across languages/source-local mappings, tied timestamps/pagination, exact Unicode/inline/partial selections, stale asynchronous responses and generated text. Validate ordinary fixtures first and assert the intended negative failure reason.

Mock transports for isolated sandbox tests. For real acceptance, exercise the actual pinned MediaWiki action/API, MariaDB vector query and Ollama embedding route, then the new browser journey. Do not credit mocked success as native integration. Run dependent browser acceptance after the live data/API integration works.

Demonstrate a real trilingual topic: semantic query → book → walk through real ordered revisions → open a historical edition → select attributable text → inspect inline history → close to the same position → change language and observe the reset. Exercise at least a second topic corridor and a cross-language discovery query. Establish query relevance expectations from article meaning before inspecting rankings; do not rewrite them to match output.

Verify native mouse/keyboard selection and the rendered result, with exact quote/range expectations. Check API failure and missing-history recovery. Keep existing Blame regression coverage and run affected checks; do not broaden unrelated tests repeatedly once meaningful checks pass.

Inspect desktop and narrow fallback visuals in one batched pass, repair concrete defects, then confirm once. Screenshots support visual evidence; they do not prove backend integration or provenance. Preserve unrelated work and live shared state during tests.

## 9. Handoff at completion or deadline

Leave a reviewable diff and documented localhost startup commands. If safely possible, leave the new demo running and verify its exact URL before sharing it. Keep generated credentials, database files, models, downloads and test session state out of Git. Commit locally by separation of concerns when appropriate; preserve incomplete work safely.

Provide:

1. Exact delivered behaviour and status for every L requirement.
2. Baseline/tested revision, app URL, ports, versions, selected topics, per-language article/revision counts, snapshot cutoffs and provenance status.
3. Commands and observed native/unit/browser results, performance measurements, repairs, and unverified claims.
4. A concise table of changed files/file groups and reasons, suitable for a later PR.
5. Total elapsed time and explicit treatment of any blocker or deadline stop.
6. Prioritised remaining work with dependencies and evidence-based effort estimates. Separate unfinished required behaviour from optional expansion; the human decides extra time.

Possible optional follow-ups: a larger curated trilingual library; scaling to the broader S corpus; richer corridor architecture and transitions; full mobile 3D; per-revision embeddings and semantic drift; generated answers with edition-specific citations; public hosting and production hardening. Do not begin these within the initial cap at the expense of required acceptance.

Do not claim the whole Wikipedia is loaded, every language history is complete, the new frontend is integrated, or a criterion passed without corresponding evidence. A visually impressive shell with broken or fictional Blame is an incomplete result.

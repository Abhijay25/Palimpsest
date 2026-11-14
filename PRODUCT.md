# Palimpsest

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Visitors exploring Wikipedia subjects and their connections. For the Library feature, the primary outcome is an impressive, exploratory knowledge universe; historical investigation is a secondary capability available within it. No narrower audience demographic was specified.

## Product Purpose

Palimpsest combines a local MediaWiki application with tools for exploring how article wording evolved. The proposed Library frontend adds spatial discovery, multilingual topic-books, historical editions, and full article reading with passage-level Blame.

## Stack

The existing application uses MediaWiki and MariaDB. For the separate Library frontend, the owner approved React/TypeScript, Three.js, and a small backend, with technical adjustments delegated to implementation after inspecting current code. The delivery target is a desktop-first localhost demo with usable mobile and reduced-motion fallbacks.

## Confirmed Library Journey

1. Explore an Interstellar-like lattice of bookshelves extending above, below, and into the distance. Guided scroll/zoom and clickable topics lead through related subjects.
2. Translations of the same topic form one topic-book with a language switch. The initial collection may be small, but every admitted topic-book must offer Finnish, Swedish, and English with real imported histories.
3. Select a topic-book and language to enter that article's first-person history corridor.
4. Walk forward from newest to oldest imported editions. Each revision appears once: newest on the left, next on the right, alternating deeper into the corridor.
5. Click an edition to pause walking and open a large book-styled overlay containing the full selectable article and inline passage-level Blame. Closing restores the corridor position.
6. Switching language opens its latest imported edition, clearly announces the date change, and clears stale selection/history. Language articles have independent revision histories.
7. Provide access to the ordinary article page with verified revision identity and source links.

## Semantic Discovery

Use multilingual bge-m3 embeddings and MariaDB vector search to relate similar subjects. Ollama embeds new text queries with the compatible model. Related articles may be found across languages. Generated answers with citations are future work.

Existing S article vectors are available as source assets; reusing validated, snapshot-aligned vectors is a recommended implementation default. Semantic placement describes article similarity, while the corridor describes revision chronology. Historical semantic drift was not requested for the initial build.

## Operating Context and Constraints

- A hard three-hour implementation cap includes inspection, data preparation, dependencies, implementation, verification, and handoff. Extra time requires a human decision. At the cap, report completed and incomplete requirements and list prioritised future work.
- The separate frontend connects to actual Palimpsest and MariaDB. The existing frontend in `/Users/zhenghaofang/Documents/ChatGPT/HackJunction` is a read-only UX reference with fictional data; preserve its code and service.
- Use actual article content, original public revisions, and verified source/local mappings. Keep incomplete coverage and uncertain attribution visible.
- Existing Blame defines colour as the revision that last changed a passage. Preserve this meaning and use labels alongside colour.
- A full article can contain generated or otherwise unmappable regions. Existing attribution limits remain visible and authoritative.
- Preserve existing MediaWiki workflows, private runtime data, and unrelated worktrees.

## Brand Commitments

Palimpsest; the Library of Babel as the metaphor for Wikipedia; an Interstellar-like bookshelf lattice and spatial time corridor; Zoomquilt-inspired continuous discovery. Books and shelves should remain recognisable. The finite curated corpus must be represented honestly even when the environment conveys vastness.

## Evidence on Hand

- Infrastructure and provenance contracts: `docs/infra/` and `scripts/palimpsest_data/`.
- S manifest observed locally: 29,460 language articles and 2,919 Wikidata groups with snapshots in all three languages. These counts do not establish imported history coverage.
- Existing seed fixture: six articles / 148 public revisions in the infrastructure handoff; none of those six topics has all three languages in the S manifest. Additional histories are needed for a trilingual topic-book.
- Implemented Blame worktree observed at `/Users/zhenghaofang/.codex/worktrees/palimpsest-blame/Palimpsest`. Its API, revision-colour requirements, and verification evidence are documented under `docs/blame/`. This worktree is active and must be rechecked; historical verification does not certify the proposed Library frontend.

## Product Principles

- Make exploration compelling while keeping every selectable destination grounded in real content.
- Keep displayed content, selected edition, language, and attribution on the same revision.
- Use space for discovery and time order; use readable selectable text for investigation.
- Preserve provenance, uncertainty, public visibility, and truthful coverage.
- End the timebox with evidence and a concrete continuation list.

## Deliberately Delegated Decisions

Choose the exact coherent trilingual collection, spatial layout algorithm, application directory, backend implementation, ports, and dependency versions after inspecting the owning sources. The implementation prompt recommends an initial three-topic minimum, growing toward three to five topics if time allows; that numerical target is an implementation default, not an explicit owner-selected count.

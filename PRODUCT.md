# Palimpsest

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Visitors exploring how Wikipedia article wording evolved.

## Product Purpose

Palimpsest combines a local MediaWiki application with tools for exploring how article wording evolved.

## Stack

## Operating Context and Constraints

- A hard three-hour implementation cap includes inspection, data preparation, dependencies, implementation, verification, and handoff. Extra time requires a human decision. At the cap, report completed and incomplete requirements and list prioritised future work.
- The separate frontend connects to actual Palimpsest and MariaDB. The existing frontend in `/Users/zhenghaofang/Documents/ChatGPT/HackJunction` is a read-only UX reference with fictional data; preserve its code and service.
- Use actual article content, original public revisions, and verified source/local mappings. Keep incomplete coverage and uncertain attribution visible.
- Existing Blame defines colour as the revision that last changed a passage. Preserve this meaning and use labels alongside colour.
- A full article can contain generated or otherwise unmappable regions. Existing attribution limits remain visible and authoritative.
- Preserve existing MediaWiki workflows, private runtime data, and unrelated worktrees.

## Evidence on Hand

- Infrastructure and provenance contracts: `docs/infra/` and `scripts/palimpsest_data/`.
- S manifest observed locally: 29,460 language articles and 2,919 Wikidata groups with snapshots in all three languages. These counts do not establish imported history coverage.
- Existing seed fixture: six articles / 148 public revisions in the infrastructure handoff; none of those six topics has all three languages in the S manifest. Additional histories are needed for a trilingual topic-book.
- Implemented Blame worktree observed at `/Users/zhenghaofang/.codex/worktrees/palimpsest-blame/Palimpsest`. Its API, revision-colour requirements, and verification evidence are documented under `docs/blame/`. This worktree is active and must be rechecked.

## Product Principles

- Make exploration compelling while keeping every selectable destination grounded in real content.
- Keep displayed content, selected edition, language, and attribution on the same revision.
- Use space for discovery and time order; use readable selectable text for investigation.
- Preserve provenance, uncertainty, public visibility, and truthful coverage.
- End the timebox with evidence and a concrete continuation list.


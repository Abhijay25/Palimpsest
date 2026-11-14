# Library implementation design

One implementation agent; separate branch and feature-owned runtime. Existing Blame and parent runtime remain unchanged. New services: three language wikis at 48181–48183, vector database at 48184, application at 5180, Ollama at 11435. Verify ports before starting. Generated data lives in ignored `.local/library/`.

React/TypeScript owns the catalog, navigation, language, selected revision and reader state. Three.js owns the guided lattice and eye-height corridor, with bounded instanced architecture. Topic grouping uses Wikidata IDs. Revision identities include language, local page/revision IDs and separately verified original IDs.

The Node backend serves the app, performs parameterised MariaDB vector queries, talks to Ollama, and proxies only configured language-wiki API endpoints. It admits only the manifest's verified pages/revisions. Database credentials are generated privately. Public wiki visibility remains authoritative; raw HTML analyses are not cached in the application.

The reader is an isolated same-origin HTML document inside a book-styled overlay. A small explicit adapter supplies the native consumer's required configuration/API/link functions, then loads the repository's actual Blame helpers, controller and CSS. This reuses the proven native exact-selection/colour/timeline implementation without leaking its document listeners across React remounts. It is an adapter, not a claim that MediaWiki globals exist naturally outside the wiki. Both native API output and the adapter are exercised in the real browser. Reader links and edition events communicate through validated same-origin messages. No synthetic history is used for product content.

Catalog metadata is served only after checking complete provenance and all three languages. The logical corridor sequence is derived from verified imported mappings, not local latest IDs. The API pins every request to an admitted local revision. Historical article placement stays anchored to its snapshot embedding. Position is an approximate semantic arrangement; chronology is separately ordered.

Frontend API: GET /api/catalog; GET /api/topics/:id/revisions?lang=fi|sv|en; POST /api/search {query}; GET /api/related/:id; configured /api/wiki/:lang proxy; GET /reader/:topic/:lang/:revision. Unknown topics, languages, and revisions fail explicitly. Search results group by topic, retaining best matched language. Latest imported means the source-anchor mapping, even if a wiki later receives local edits.

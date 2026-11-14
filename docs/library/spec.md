# Library specification

Approved brief: IMPLEMENTER_PROMPT.md and PRODUCT.md. Owner authorised implementation on 2026-11-14. Branch `feature/library`, baseline `74fa014f63b50669925d8a0bd964d5383f8038af`.

Timebox: start 2026-11-14 10:21:26 UTC; implementation deadline 13:21:26 UTC. Reserve 13:06:26–13:21:26 for verification and handoff.

L01–L12 in the implementation prompt are the acceptance requirements. The initial target is three trilingual topic-books: Luntoberget, Krejansberget, and Round Tower (Vyborg). They connect Finnish historical landscapes and built heritage; the two Siuntio Bronze Age sites form a meaningful related pair. Every displayed article needs original public history through its S anchor, source/local reconciliation, and actual native Blame readiness.

Discovery is guided through a semantic bookshelf lattice. A selected book/language opens one first-person corridor. Editions alternate left/right exactly once, newest to oldest, ordered by actual timestamp and revision ID. A bounded visible window preserves access to the entire imported sequence. A readable overlay pauses scene motion, preserves native inline Blame, and closes to the stored camera position. A language switch deliberately opens its latest imported edition and announces the date change.

Search embeds queries using local bge-m3 through Ollama and executes native MariaDB cosine vector search. Article vectors remain aligned with S anchors. Generated answers, historical semantic drift, public hosting, and full mobile 3D are deferred. Reduced-motion/mobile/WebGL fallback uses the same real catalog and reader.

Frozen relevance expectations, derived from source article text before querying: a query about a Vyborg tower built in 1547–1550 should retrieve Round Tower first; a query about Bronze Age burial mounds in Siuntio should retrieve Luntoberget or Krejansberget; Finnish/Swedish paraphrases of those subjects should find the same topic identities.

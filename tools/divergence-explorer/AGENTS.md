# Divergence visualization context

This is an independent optional Python/Flask viewer. It does not modify MediaWiki core, configure the three-wiki runtime, or require the unpublished NeoWikiReview extension branch. Keep the PR focused on this tool. The original extension worktree is separate.

One row means one provisional underlying semantic disagreement/question. Repeated passages, language pairs and historical occurrences belong inside that row. No six-topic cap, fixed centroid count, English introduction seeds or assumption of parallel article structures. The bundled run uses symmetric all-eligible-prose chunk matching, MariaDB cosine top-3 both ways, parallel Decisions predicates, then nearest-representative same-disagreement predicates. The engine itself is external to this viewer.

The committed public sample has 520 provisional tracks, 5,005 occurrences, 26 checkpoints spanning 2020 through July 16, 2025. Categories in this run are coverage and framing; none passed the strict contradiction gate. Counts are not verified atomic facts. Annual dashed spans have unknown continuity. Missing matches are not whole-article omissions; missing phases do not prove resolution. Historical rendered HTML may contain newer transclusions.

Default operation reads the compressed public sample without Docker, MariaDB, credentials, models or API spending. An explicit loopback engine option can read live prepared summaries and forward a CSRF-protected enrichment request. GET never starts preparation or paid calls. Enrichment is disabled for the bundled sample. Preserve original sources, revision links, selected-pair isolation, current edition on the left, and one-day minimum zoom. Do not publish Wikipedia edits.

The exporter allowlists fields; never export the shared API cost ledger, environment files, keys, credentials or local paths. Wikipedia source excerpts are CC BY-SA 4.0 with attribution and exact revision URLs in the bundle. Keep the checksum manifest current after changing the artifact.

Run `python -m unittest discover -s tests/divergence -v` and `node --check tools/divergence-explorer/static/discrepancy-explorer.js`. Check desktop/mobile using the in-app browser. Existing infra/runtime tests remain separate; do not bypass disk guards or start/rebuild the native stack to test this standalone viewer.

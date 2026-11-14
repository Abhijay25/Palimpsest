# Existing research implementation

This directory is a direct copy of the working `language-gap-explorer` research app, including its current uncommitted comparison/explorer work. `SOURCE_MANIFEST.json` records the original source commit and the SHA-256 of every copied source file. Preserve this migration boundary: do not replace working explorations with new implementations as part of the port.

Subsequent approved iteration: `feature/divergence-skyline` replaces this app's horizontal-line overview with calendar columns and a cached question-list handoff to the existing tracker. The manifest remains provenance for the original port; Git records these subsequent UI changes. The comparison/preparation algorithm remains the existing symmetric pipeline.

`skyline.py` aggregates one question once across all selected pairs, chooses actual supporting occurrences, and adapts exact stored historical evidence for `/langcompare/<topic>?run=…&group=…&stamp=…`. Historical requests must fail explicitly instead of falling back to snapshot results. `static/skyline-model.js` bins the latest assessed observation per calendar period; unknown bins are not zero and observations are never summed. Source reads and navigation cannot invoke Decisions.

Prepared EN/FI/SV Winter War results: 324 all-time provisional questions, 3,535 occurrences, 26 checkpoints, 40 source revisions, ending July 29, 2025. The latest observation has 128 questions: 116 coverage, 12 framing, zero contradictions. All stored quote offsets, checkpoint timestamps and dataset-anchor cutoffs were audited. The older 520-question EN/FI/RU cohort is separate.

Use `NEOWIKI_RESEARCH_ROOT` to reuse an existing ignored research runtime root. Do not copy its environment, caches or spending ledger into Git. For an alternate preview port: `python -m flask --app app run --host 127.0.0.1 --port 8022` from this directory.

Read the repository [exploration registry](../../docs/explorations/README.md) and root `AGENTS.md`. The independent experiments here are the snapshot language reviewer, confirmed passage watchlist, Tornedalians article/update showcase, Winter War edit-event timeline, superseded reference-led history experiment, symmetric historical comparison engine and full-viewport divergence explorer. The native MediaWiki extension is a separate unpublished branch.

`app.py` serves the existing article/comparison/update workspace on localhost:8010. `explore_preview.py` is the lightweight independent viewer on localhost:8020. Both read the existing research MariaDB on localhost:3310. `setup.ps1` explicitly installs dependencies/models and acquires/imports research data; do not run setup, duplicate a database or queue inference merely to inspect the port. The database, datasets, `.env`, model caches and generated reports are not committed. The database-free packaged viewer from PR #4 remains under `../divergence-explorer`.

The source README is historical research documentation. Its old fixed $10 references are superseded by the current `live_api.py` implementation: `NEOWIKI_API_TOTAL_LIMIT_USD` is optional, with successful call caching and retained failed reservations. No worker runs automatically on page reads. Never commit credentials or the private API spending ledger, reset reservations, or publish Wikipedia edits.

Current edition stays left/first. Historical counterpart versions must not exceed either the event/checkpoint timestamp or their dataset anchors. Retrieval is not proof of equivalence or omission. One semantic divergence track groups repeated occurrences of the same provisional underlying question. The active symmetric engine is `paired_history.py`, not the six-English-seed discovery path retained in `historical_divergence.py`. Historical helpers in that older module are still used by the working engine.

Verification for this source port uses the existing isolated suite, run with this directory as cwd:

```sh
python -m unittest test_paired_history test_historical_divergence test_discrepancy_explorer test_showcase test_update_issues test_decisions_only
python -m unittest test_skyline
node test_skyline_model.js
```

These tests do not download models or invoke the provider. Other source tests/browser scripts have database, model or runtime requirements; distinguish their fixtures, stored observations and actual live runs. See `PORT.md` for the migration boundaries.

## Searchable heatmap iteration

`static/heatmap.js` now drives `/explore`; the old skyline-only JS remains as provenance and is no longer loaded. A compact all-question skyline sits above a virtualized question matrix. The real cohort is unchanged: 324 all-time questions, 313 represented by the latest observations in the initial yearly columns, 128 in the latest checkpoint. Do not confuse these scopes. Rows are unbounded and scrollable; only visible rows are rendered. Year/Month/Week/Day buttons, period navigation, double-click zoom, category/pair filters, observed category-change filtering and keyboard arrows operate on stored data. Borderless adjacent colored cells provide visual continuity; explicit unknown gaps and the sampling notice must remain. A missing row finding is not agreement or resolution.

`heatmap.py` caches a bulk selected-evidence catalogue. `GET /explore/api/matrix` and `/cell` perform no model work. The explicit CSRF-protected `POST /explore/api/search` combines BM25 over source-derived labels and selected representative excerpts with MariaDB cosine similarity to their existing multilingual vectors. Local E5 query embeddings use `embedding_model(local_files_only=True)` and a bounded query cache. No model download, Decisions call, translation generation or new historical assessment is part of search. Semantic retrieval contributes at most 40 candidates above the heuristic similarity threshold; keyword matches are uncapped. This search limit is not a discovery/topic cap. If the local model is unavailable the UI explicitly reports keyword fallback.

“Most controversial” is an explained ordinal sort: possible contradiction, framing, then context, scoped to displayed observations and actual pair classifications. It does not use passage counts or claim calibrated controversy. Pair-specific category metadata and exact occurrence IDs survive the evidence preview and historical article handoff. Search, filters, selected cell, observation, scroll and date window are kept in the return URL. Initial label text uses source sections/question types, without new generated summaries.

Checks: `python -m unittest test_heatmap test_skyline test_paired_history test_historical_divergence test_discrepancy_explorer test_showcase test_update_issues test_decisions_only` (61 checks), `node test_skyline_model.js`, `node --check static/heatmap.js`, plus the independent viewer's 15 tests. Browser verification covered desktop/mobile, hybrid search against real vectors, seven-day view, monthly zoom, bottom-sheet evidence, exact EN–SV and FI–SV destinations, browser-back restoration, keyboard arrows, all 313 currently displayed rows through virtualization and zero console errors. No Decisions calls were made. Native MediaWiki and the independent viewer remain untouched.

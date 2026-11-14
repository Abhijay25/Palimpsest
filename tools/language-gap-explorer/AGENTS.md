# Existing research implementation

This directory is a direct copy of the working `language-gap-explorer` research app, including its current uncommitted comparison/explorer work. `SOURCE_MANIFEST.json` records the original source commit and the SHA-256 of every copied source file. Preserve this migration boundary: do not replace working explorations with new implementations as part of the port.

Read the repository [exploration registry](../../docs/explorations/README.md) and root `AGENTS.md`. The independent experiments here are the snapshot language reviewer, confirmed passage watchlist, Tornedalians article/update showcase, Winter War edit-event timeline, superseded reference-led history experiment, symmetric historical comparison engine and full-viewport divergence explorer. The native MediaWiki extension is a separate unpublished branch.

`app.py` serves the existing article/comparison/update workspace on localhost:8010. `explore_preview.py` is the lightweight independent viewer on localhost:8020. Both read the existing research MariaDB on localhost:3310. `setup.ps1` explicitly installs dependencies/models and acquires/imports research data; do not run setup, duplicate a database or queue inference merely to inspect the port. The database, datasets, `.env`, model caches and generated reports are not committed. The database-free packaged viewer from PR #4 remains under `../divergence-explorer`.

The source README is historical research documentation. Its old fixed $10 references are superseded by the current `live_api.py` implementation: `NEOWIKI_API_TOTAL_LIMIT_USD` is optional, with successful call caching and retained failed reservations. No worker runs automatically on page reads. Never commit credentials or the private API spending ledger, reset reservations, or publish Wikipedia edits.

Current edition stays left/first. Historical counterpart versions must not exceed either the event/checkpoint timestamp or their dataset anchors. Retrieval is not proof of equivalence or omission. One semantic divergence track groups repeated occurrences of the same provisional underlying question. The active symmetric engine is `paired_history.py`, not the six-English-seed discovery path retained in `historical_divergence.py`. Historical helpers in that older module are still used by the working engine.

Verification for this source port uses the existing isolated suite, run with this directory as cwd:

```sh
python -m unittest test_paired_history test_historical_divergence test_discrepancy_explorer test_showcase test_update_issues test_decisions_only
```

These tests do not download models or invoke the provider. Other source tests/browser scripts have database, model or runtime requirements; distinguish their fixtures, stored observations and actual live runs. See `PORT.md` for the migration boundaries.

# Blame development and verification

The feature is a MediaWiki extension under infra/wiki/extensions/PalimpsestBlame. The parent infrastructure source/history pipeline remains separate. Execute setup from this feature branch; do not copy the standalone frontend demo into the wiki.

## Teammate setup

Docker/Compose and Python3.11+ are the same prerequisites as the infrastructure README. No host PHP, Node or browser package installation is required.

```sh
python3 scripts/wiki setup
python3 scripts/wiki verify --scope runtime
```

Setup enables the extension, creates its derived tables and starts its queue workers. After switching an existing runtime to this branch, rerun setup to refresh schemas, then use down/up to reload long-running workers; data persists. Do not use reset to upgrade.

A fresh wiki has local history only. Create/edit a page to explore its local attribution, or acquire the explicit real six-page sample:

```sh
python3 scripts/wiki history probe-anchors --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki history acquire --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data support --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data import --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki verify --scope sample --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/blame_provenance.py --data-root .local/wiki --manifest tests/data/fixtures/sample-corpus.json --install
```

Support and import may return nonzero while rendering dependencies are incomplete, even after all six article histories import successfully. Inspect their reports and the separate sample verifier; never ignore a source/history/mapping failure. Provenance export requires the requested histories fully reconciled against the live runtime and refuses corrupt, incomplete, hidden or changed records. It publishes checksummed operator-trusted metadata, not cryptographic signatures or independently authenticated Wikipedia accounts. Its --install option places only each language's metadata in that wiki's existing read-only config mount.

Select the Blame action alongside Read/View history. Date navigation changes the displayed snapshot and its attribution together. A selection spanning contributors opens its exact wording history directly beneath the selected statement. Generated/template text without a proven source range remains unannotated. Source and local revision IDs differ; imported author names do not create authenticated source-wiki accounts locally.

After sample import/export, try Finnish Myyntimies Jethro matkoilla or Seppo Rapo, Swedish Patis kyrka, and English Ulf Grönholm or Seppo Särkiniemi. A fresh empty wiki also supports Blame on pages you create and edit locally, without downloading Wikipedia data. The sample contains six articles and 148 original revisions; it does not include all 29,460 S articles.

Manual check: open Blame; click a highlighted word or select a phrase and choose Inspect selected text; expand a wording-history entry; compare its predecessor; interpret then apply an as-of/range query and choose a result; return to latest; edit the page and inspect the new local attribution. Source anchors and latest local edits are shown separately. Close history before making a new selection that crosses the inline controls.

For custom project/data-root/ports, use identical common options for every wiki command and pass the same absolute data root to the provenance exporter. Do not copy another runtime's C4 maps or DB credentials. Keep all generated state private/ignored.

## Checks and evidence

- Root exporter tests: python3 -m unittest discover -s tests/blame_provenance -v
- PHP algorithm/mapper tests live in the extension's tests/php directory; use the pinned MediaWiki container with a read-only extension mount.
- Pure JS and actual Chromium DOM tests live in tests/js. The cached pinned Playwright image includes a bundled Node runtime, avoiding dependence on a host installation.
- Independent synthetic, actual API and browser acceptance lives in tests/blame; see its runbook after integration.
- docs/blame/verification.md records actual executed results, final revision, model/platform, semantic findings/repairs and limits. Do not infer native backend acceptance from mocked UI tests.

The opt-in `scripts/blame_verify_controls.py` temporarily changes only served metadata copies in the explicitly confirmed isolated palimpsest-blame test runtime and restores them. Its optional local-edit probe restores article wording through a real subsequent edit. The job/privacy control additionally requires temporary revision-deletion rights for that disposable administrator; the pinned default excludes this right. Never run these mutation probes against another teammate's wiki or original source caches. They are separate from ordinary offline CI.

Prototype caps are 200 synchronous / 2,000 queued revisions; 2 MiB synchronous / 16 MiB queued source history; 20,000 tokens per revision and 200,000 cumulative tokens; 250,000 LCS cells per changed pair; 1,000,000 charged lineage references; 2 MiB API responses; 64 selection ranges; and three active current-version jobs per wiki. Jobs process at most three revisions per batch by default. Derived caches have page/revision/algorithm/schema identity and recheck current visibility/provenance. Requests exceeding a supported budget fail explicitly; scale-up remains separate.

Full S seeding, full historical rendering, native mobile devices and Wikipedia deployment parity are independent limits. The feature never fabricates unavailable attribution, citations or editor intent.

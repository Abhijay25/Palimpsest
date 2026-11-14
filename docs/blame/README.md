# Blame development and verification

The feature is a MediaWiki extension under infra/wiki/extensions/PalimpsestBlame. The parent infrastructure source/history pipeline remains separate. Execute setup from this feature branch; do not copy the standalone frontend demo into the wiki.

## Teammate setup

Docker/Compose and Python3.11+ are the same prerequisites as the infrastructure README. No host PHP, Node or browser package installation is required.

```sh
python3 scripts/wiki setup
python3 scripts/wiki verify --scope runtime
```

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

For custom project/data-root/ports, use identical common options for every wiki command and pass the same absolute data root to the provenance exporter. Do not copy another runtime's C4 maps or DB credentials. Keep all generated state private/ignored.

## Checks and evidence

- Root exporter tests: python3 -m unittest discover -s tests/blame_provenance -v
- PHP algorithm/mapper tests live in the extension's tests/php directory; use the pinned MediaWiki container with a read-only extension mount.
- Pure JS and actual Chromium DOM tests live in tests/js. The cached pinned Playwright image includes a bundled Node runtime, avoiding dependence on a host installation.
- Independent synthetic, actual API and browser acceptance lives in tests/blame; see its runbook after integration.
- docs/blame/verification.md records actual executed results, final revision, model/platform, semantic findings/repairs and limits. Do not infer native backend acceptance from mocked UI tests.

Full S seeding, full historical rendering, native mobile devices and Wikipedia deployment parity are independent limits. The feature never fabricates unavailable attribution, citations or editor intent.

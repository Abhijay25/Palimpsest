# Dataset and history pipeline

This pipeline keeps the S release assets, original public revision history, MediaWiki import XML, source/local ID mappings and coverage reports under the configured data root. The tracked lock is `datasets.lock.json`; runtime databases and fetched corpus data do not belong in the Git checkout.

## Fetch and membership

```sh
python3 scripts/data.py --project palimpsest-b --data-root /path/to/palimpsest-data --ports 28081,28082,28083 dataset fetch
```

`dataset fetch` downloads each `s-2026-10` asset to `dataset/raw`, keeps interrupted `.part` downloads for a checked HTTP Range resume, and verifies both the locked length and SHA-256 before renaming. Existing files must match the lock exactly. Membership parsing runs in the pinned PyArrow tooling container and writes `dataset/manifests/full-corpus.json` plus a deterministic two-page-per-language `sample-corpus.json`. It rejects schema/count changes, duplicate source page or anchor IDs, and missing fields. It retains the original Parquet assets, including text, vectors, and Finnish category files, plus the release README's attribution and license notice.

The lock records the release API's published SHA-256 asset digests. A future release needs an explicit lock update after its release metadata and expected counts are reviewed. The tooling pins the multi-platform Python 3.12.12-slim-bookworm image by OCI index digest and PyArrow 22.0.0. The retained source README states that Wikipedia text is CC BY-SA 4.0 and asks users to credit Wikipedia and link to the article URL; do not infer a separate license for the dataset builder or embeddings.

## Anchor spike and history acquisition

Run the bounded real source check first:

```sh
python3 scripts/data.py --project palimpsest-b --data-root /path/to/palimpsest-data --ports 28081,28082,28083 history probe-anchors
```

The checked-in `tests/data/fixtures/sample-corpus.json` contains six actual S members selected by SHA-256 order over `(release, source_wiki, source_page_id)`. The spike asks for only the anchor and one older revision for each member, stores raw text plus metadata in `reports/anchor-spike.json`, and returns nonzero if page ID, revision ID, source timestamp, raw text, or source SHA-1 disagrees. This is a probe, not full history acquisition.

Sample history is resumable and remains limited to the explicit manifest:

```sh
python3 scripts/data.py --data-root /path/to/palimpsest-data history acquire --sample-manifest tests/data/fixtures/sample-corpus.json
```

Acquisition checks free space before starting and before each durable history batch. The sample default is a 2 GiB free-space floor; adjust with `--min-free-gib`. Full-history acquisition requires both `--all-pages` and an explicit `--min-free-gib 50` or higher preflight. If a later check fails, the current continuation remains at its last committed batch and can resume after capacity is restored.

Each page has committed JSONL batches and an atomic `state.json`. Batch bytes and checksums are written before a continuation checkpoint advances. On resume, committed batches are rechecked; an uncheckpointed batch is recovered only after checksum, page identity, and revision-identity validation, then recorded as a recovered orphan. A repeated continuation token, source conflict, retry exhaustion, missing anchor, hidden source field, or parent gap remains explicit in the page state. Retries are finite; acquisition failure for one page is recorded while remaining sample pages continue.

The default source is the public MediaWiki API for all three languages. The M dataset is not used until page/anchor overlap is separately measured and its revisions are reconciled. `history acquire` refuses the full manifest unless `--all-pages` is supplied. Do not use that option for ordinary verification or before the long-run data-root and rate-budget checks are approved.

## Supporting content and import

`data support` walks templates, Scribunto modules, and TemplateStyles at or before each sample anchor timestamp, respects the template/module namespace allowlist, reports missing/hidden dependencies and cycles, and records each source revision and content hash separately from S membership. It defaults to 50 API requests across the sample and 1,000 pages per root; both limits are configurable. A per-root progress file is atomically updated after each lookup. If the request budget or source rate limit stops traversal, the partial inventory lists pending titles and can resume with a later larger `--max-requests` value. Its live source resolver uses the API timestamp boundary and validates returned timestamps. The inventory is a sampled closure, not proof of exact historical rendered output.

`data import` requires completed, anchor-validated page histories, C1 runtime status, supporting inventories, and the runtime worker's `exec --language` bridge. It emits MediaWiki XML and invokes the supported `maintenance/run.php importDump` command. The wiki service must see the `imports` subtree read-only at `/data/imports` (or the explicit `--container-data-root` mount path); generated XML paths are reported in C4. The bridge must preserve argument boundaries and child exit codes. No direct MediaWiki database writes are used.

Reconciliation queries each local page and maps by observed local page ID plus exact timestamp and content hash. C5 independently joins each C4 row to its checked C3 source revision (including batch checksum and metadata), then queries local page history to verify the local IDs, timestamps, content hashes, author/comment/minor/model fields, and parent chain. Source IDs are never treated as local IDs. Hidden or ambiguous source text is never replaced by an empty string. A repeated import skips already reconciled source revisions, so an existing local edit remains current; partially imported pages export only source revisions that do not already match.

Supporting namespaces are imported separately from corpus pages and use separate C4 files. They do not increase S membership counts. External CSS, images and other non-template render dependencies are reported outside this traversal.

## Coverage

```sh
python3 scripts/data.py --data-root /path/to/palimpsest-data verify --scope sample --sample-manifest tests/data/fixtures/sample-corpus.json
```

`coverage.json` follows C5 and has a nonzero exit code until the requested source inventory and mappings reconcile with exact expected membership and no unresolved required source exceptions. Runtime health, sample status, history counts, import mappings and rendering dependency coverage are independent fields. A sample pass cannot establish full membership or history completeness.

## Readiness and evidence boundary

- S release assets are checksum-verified during fetch; downloaded Parquet membership is counted from the actual three language files in the pinned tool image.
- The committed sample manifest identifies real articles. Its live anchor-spike evidence is kept with the external data root, not committed with source code or copied into this checkout.
- No full histories are acquired as part of this sample spike.
- MediaWiki maintenance import and live container reconciliation depend on A's runtime bridge and mount. They must be exercised against the integrated runtime before T06/T09 can pass.

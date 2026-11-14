# NeoWiki divergence explorer

A prompt-first, full-viewport timeline of disagreements across Wikipedia language editions. Search a prepared topic, choose language pills, then hover a track, select a period and drill into exact source occurrences. One provisional semantic question occupies one row; repeated mentions do not add rows. Time zoom stops at one day.

## Run

From the repository root, using Python 3.11+:

```sh
python -m venv .venv-divergence
# Activate that environment using your shell's normal activation command.
python -m pip install -r tools/divergence-explorer/requirements.txt
python tools/divergence-explorer/app.py
```

Open <http://127.0.0.1:8021/explore>. The default sample needs no database, Docker, model downloads, API key or inference calls. The server binds only to loopback. This optional research tool is independent of the native MediaWiki runtime; it does not install an extension or alter wiki schemas, jobs or pages.

## Real sample and interpretation

Winter War includes **520 provisional tracks**, **5,005 evidence occurrences** and **26 historical checkpoints**, from January 2020 through July 16, 2025, in EN/FI/RU. Annual overview samples are supplemented with 20 cached recent edit checkpoints. Earlier intervals are not exhaustive revision histories. Tornedalians provides existing EN/FI/SV snapshot findings; their start/end dates and shared semantic grouping are unknown.

The Winter War run found passage coverage and framing differences. **No pair passed its strict contradiction gate.** The legend describes supported categories, not fabricated examples. Model classifications and semantic grouping require review. Paragraphs can contain multiple claims; these are not verified counts of atomic factual disagreements. Retrieval misses are not omissions, and absence of a phase is not resolution. Annual dots and dashed connectors do not establish continuous lifetimes. Historical rendered HTML may include newer transclusions.

The engine that generated the sample chunks every selected article independently (target 280 tokens, cap 400), embeds with multilingual E5-small (384 dimensions), and retrieves MariaDB exact cosine top-3 neighbours in both directions within pinned revisions. Decisions assesses relatedness, scope, contradiction, framing, passage coverage and compatibility in parallel batches. Actionable pairs are grouped through nearest pair/representative candidates and >= .88 same-underlying-disagreement predicates, without a fixed number of clusters. Contradiction requires incompatibility >= .85 and same scope >= .80, after relatedness >= .60. Titles are neutral question templates plus both source section names, not generated factual claims or English introduction anchors.

This PR packages the visualization and data boundary, **not the historical ingestion/classification worker**. The engine's cached output is included so reviewers can run the actual visualization independently. See the readable [sample manifest](sample/wikipedia-history.json.manifest.json) for checksums and source counts. Full revision attribution is in the compressed bundle's `provenance.sources`.

## Connect the existing engine

```sh
python tools/divergence-explorer/app.py --engine-url http://127.0.0.1:8020
```

This explicitly switches reads to an already running local discrepancy engine implementing `/explore/api/history`, `/cached`, `/details` and `/enrich`. Only HTTP loopback origins are accepted. Topic queries still require prepared engine data; opening the viewer never queues inference. Progressive summaries are polled during a running preparation, with skeletons before results arrive. The dense graph uses lightweight segments, cached date formatting and row-level hit testing; evidence is fetched separately.

In connected mode the **Get translations & highlights** button explicitly forwards a protected enrichment request. The engine owns its own API budget, cache, source visibility and classification rules. Translation can use local Argos models; qualifying contradiction highlighting can use Decisions token predicates. The viewer has no API key and makes no provider calls itself. The bundled sample permits only already-cached translations/highlights; that enrichment button is disabled.

## Export a new prepared bundle

Run the exporter using the existing prototype environment (Flask and PyMySQL already installed there):

```sh
python tools/divergence-explorer/export_bundle.py \
  --prototype-root /path/to/language-gap-explorer \
  --output /path/to/prepared.json.gz
python tools/divergence-explorer/app.py --bundle /path/to/prepared.json.gz
```

The exporter reads completed `paired_run` / `paired_occurrence` records and cached Tornedalians findings. It never prepares data or invokes a model. It allowlists public fields, validates Wikipedia revision URLs and checkpoint cutoffs, excludes cost ledgers/secrets/local paths, and writes a reproducible gzip plus checksum manifest. Currently its source adapter targets `symmetric-disagreements-v1` and these two prepared topics. This is a presentation export, not a backup of canonical wiki entities.

## Checks and provenance

```sh
python -m unittest discover -s tests/divergence -v
node --check tools/divergence-explorer/static/discrepancy-explorer.js
```

Tests cover actual bundled sources, referential integrity, grouping occurrences into rows, language-pair isolation, cached reads, validation, enrichment CSRF and the optional engine bridge without provider calls. CI runs these separately from the existing MediaWiki infrastructure suite. Browser verification details are recorded in [verification.md](verification.md).

Wikipedia excerpts and adaptations are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), attributed to **Wikipedia contributors**. Each excerpt links its original revision, whose page history identifies contributors. Normalization, excerpt selection, model labels and provisional grouping are modifications. Cached machine translations can contain errors. The public sample does not export API credentials, spending information, a database or model weights.

The graph and time navigator take inspiration from [Histography](https://histography.io/); no assets, scripts or audio from that site are included. This tool is an independent research prototype and is not endorsed by Wikipedia or the Wikimedia Foundation.

# Semantic disagreement history explorer

Open <http://127.0.0.1:8020/explore>. Run the standalone preview with `.venv/Scripts/python.exe -B explore_preview.py`. The existing application also registers the blueprint after its next restart. The original reader, comparison tracker and edit-event timeline remain separate.

## Current behavior

A centered prompt asks “View divergence in [topic] for [languages]”. Both inputs start blank. Winter War opens real historical comparisons for English, Finnish and Russian. Tornedalians opens existing real snapshot observations, whose lifetimes and semantic grouping are unknown. Search currently recognizes these prepared topics, their article URLs and IDs; arbitrary free-text semantic topic discovery is not implemented.

The graph fills the viewport. One row represents one **provisional underlying disagreement/question**, with repeated passage matches and language pairs attached as occurrences. There is no six-topic cap or predetermined number of centroids. Dense tracks reveal their labels on hover/focus. The bottom brush and zoom controls stop at a one-day window; multiple same-day source checkpoints remain inspectable. A floating inspector leads to a separate evidence drawer, with occurrence selection and period navigation. The current edition stays left/first; a missing current edition gets an explicit placeholder.

Colors are discrete: additional passage context, different framing, possible contradiction. They are model judgments, not calibrated divergence values, truth, national bias or editorial intent. Unmatched retrieval and compatible passages cannot create disagreement rows. A missing row/phase is not evidence of resolution. Annual observations have colored points and dashed connectors: those connectors do not establish continuous persistence.

Histography inspired the spatial graph and bottom navigator. Wikipedia blue, white surfaces and the established typography are retained; no Histography assets are copied.

## Real historical pipeline

Explicit preparation: `.venv/Scripts/python.exe -B paired_history.py --since 2020-01-01 --languages en,fi,ru --workers 6`.

1. Reuse pinned historical sources, annual as-of snapshots for 2020–2025 and 20 recent cached edit checkpoints (26 checkpoints total). Each edition revision must be at or before the checkpoint and its dataset-era anchor. The common endpoint is July 16, 2025; this is not live 2026 Wikipedia. Historical rendered HTML can contain newer transclusions.
2. Chunk **all selected editions independently**, using the existing paragraph/token normalizer: target 280 tokens, hard cap 400. Validate exact character offsets against cached revision prose. Repeated identical text retains every source location.
3. Reuse local multilingual E5-small embeddings, normalized 384 dimensions. MariaDB exact cosine top-3 candidates are retrieved in **both directions**, restricted to the selected counterpart revision. Batched SQL avoids sorting a global historical distance matrix. There are no English introduction seeds, shared section-structure requirements or six reference topics.
4. Assess new exact bilingual chunk pairs with Decisions: six predicates plus a question-type choice per pair, 16 pairs per request, six concurrent request workers. Relatedness below .60 is retrieval failure. Contradiction requires incompatibility >= .85 and same scope >= .80; framing and passage coverage use .80. Refusals/missing results are unassessed. Coverage means extra information in a compared passage, never proven absence from an entire article. No generative extraction/title API is used.
5. For actionable differences, form a normalized pair embedding from both source vectors. Retrieve nearby pairs and existing representatives (top eight each). Batch same-underlying-disagreement predicates; merge only at >= .88 against a fixed representative. This creates a variable number of groups, avoids transitive chains, and attaches repeated evidence to one topic. Titles combine a neutral question template with both source section names. The finite question-type choices do **not** limit the number of semantic groups.
6. Store exact occurrences by group/checkpoint and publish an overview newest-first. Identical text-pair verdicts and grouping judgments are reused across revisions. Resume completed checkpoints after an interrupted job. API failures are retained without automatic provider retries. Opening a DB connection has bounded local retries; progress updates are small writes rather than repeated full-source rebuilds. For future cold runs, prioritized high-similarity pairs can produce an initial grouped preview after at least 64 assessments, while the remaining batches continue. This scheduling change has an isolated batch/progress test; the completed backtest used the earlier whole-checkpoint preview boundary.
7. The browser polls stored lightweight summaries, showing skeletons before rows appear. Opening a row fetches exact sources separately. An explicit CSRF-protected enrichment action runs local Argos translations and, for qualifying contradiction occurrences, cached token predicates for highlights. No translations/highlights block the overview.

## Storage and API boundaries

Shared `divergence_vector`, `divergence_revision` and `divergence_passage` cache source vectors and revision membership. `paired_run` stores configuration, progress, summary and error state. `paired_matches` caches symmetric retrieval; `paired_verdict` caches exact pair assessment; `paired_feature`, `paired_group_check`, `paired_topic` and `paired_assignment` store provisional semantic grouping. `paired_occurrence` stores exact paired sources, offsets, revision links, classification support and optional enrichment. Original snapshot/showcase tables are preserved.

- `GET /explore/api/history`: stored overview only, filtered by actual selected occurrence pairs. A third edition's contradiction cannot leak into a different selected pair.
- `GET /explore/api/details`: original stored occurrences only, scoped to selected languages. No provider/model/download work.
- `POST /explore/api/enrich`: session token required; accepts stored occurrence identities, never arbitrary replacement source text. Translations are local. Contradiction highlights can make an explicitly requested Decisions call and are cached.
- `GET /explore/api/cached`: existing Tornedalians findings as snapshot points. These are not silently relabeled as real lifetime tracks.

Source rendering uses text nodes, validated highlight offsets and revision URLs. The shared API ledger reserves and caches costs. The user revoked the old $10 limit; an optional environment ceiling remains available. Cost figures are metered estimates, not an invoice. Never print or commit environment secrets. GETs cannot start preparation or spend.

## Limits and interpretation

Grouping is provisional. A paragraph may contain several claims, and only the dominant assessed difference is represented; there is no exhaustive atomic-claim extraction. Candidate-limited representative matching can leave duplicate groups or merge related differences incorrectly. Human merge/split review and systematic clustering evaluation remain future work. Row counts depend on language choice, chunking, thresholds, source coverage and grouping, so they are not ground-truth counts of Wikipedia errors.

Annual snapshots are sparse samples. Only the cached recent edit window enumerates the selected source edits, not every revision since 2020. Missing retrieval, failed assessments and unobserved gaps are not omissions or resolved issues. Dedicated sentiment scoring, unrestricted semantic-topic search, live revision ingestion and automatic Wikipedia editing are not implemented.

## Validation

38 targeted offline tests pass across semantic row grouping/counting, selected-pair isolation, strict classification, source reads, CSRF, source offsets and existing tracker regressions. JavaScript syntax passes. The optional `check_discrepancy_explorer.py` now targets prepared real data and has not been run for this revision; browser interaction checks use the in-app browser. Earlier fixture screenshots/scripts describe older layouts and are not evidence of this pipeline's accuracy.

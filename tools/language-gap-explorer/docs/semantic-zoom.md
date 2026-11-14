# Semantic zoom: questions → months → years

**Latest presentation:** bare `/explore` is the centered article/language prompt. The main results use Wikipedia styling, a compact floating toolbar and one viewport-filling monthly histogram across the available source range. Zoom changes the date window and adapts to yearly buckets for longer spans; month is the finest time unit. Clicking a bucket opens its searchable issue table rather than zooming. Click an issue to open a wide side-by-side evidence dialog; selected-question deep links restore it directly. The obsolete constellation view, template and static assets are deleted; older sections below record implementation history. The `/explore/api/constellation` backend name remains a supported paginated question API used by the main UI.

The source pane explains observed differences using exact passages, machine translations, highlights, revision provenance and the existing article discrepancy tracker. Draft editing was explicitly removed from the visualization's scope: its purpose is awareness and understanding for readers and editors.

`GET /explore/api/showcase` exposes the curated 20-article Finnish-history collection, actual ready/partial/preparation states, source cutoff and latest/all-time counts. It is read-only. Optional `/cell?occurrence=...` preserves a specific stored occurrence, including a weaker category selected within a stronger aggregate group. An invalid or out-of-scope identity fails explicitly.

```sh
python -B article_pipeline.py showcase
python -B article_pipeline.py enqueue --showcase --mode snapshot
python -B article_pipeline.py worker --workers 2
python -B article_pipeline.py status
# Resume a selected interrupted article; failed provider reservations stay retained:
python -B article_pipeline.py resume --topic Q134949
python -B question_titles.py worker --workers 2
```

The worker uses two concurrent article jobs with at most two requests each, while shared provider limits remain six total and two title-generation slots. Successful cached assessments may publish as a visibly partial checkpoint when other calls are unavailable; those unavailable cases remain unassessed. Unknown same-question checks defer possible duplicates instead of creating extra question identities. No failed paid request is silently reset or resent. See the [judge walkthrough](../../../docs/hackathon-walkthrough.md) and [data status](../../../docs/hackathon-data-status.txt).

The active research app keeps one visualization on screen. Its latest assessed month opens as equal-size question dots. Hover/focus gives the specific question, category, actual language pair and observed date; selection opens the existing historical article tracker. Zoom out reveals monthly blobs, then yearly blobs. Browser Back preserves the article, selected languages, run, period, search and observation. Search opens from the magnifier rather than occupying permanent chart space.

## Counting and evidence

A year/month blob counts the union of distinct semantic-question IDs observed anywhere in the UTC period. Repeated mentions, pairs and checkpoints never inflate its total. Each question uses the strongest actual selected-pair category in that period. Children overlap: a recurring question can appear in several months, so do not sum month totals to produce a year. The month's question count matches its parent blob. Positive blob area follows count; all question dots are equal size.

Unknown periods and periods outside source anchors are dashed placeholders. Completed observations with zero findings are explicit zero. Absence of a finding is not proof of agreement, resolution or continuity. The date selector exposes the latest eligible checkpoint per UTC day, while the month union retains every stored observation.

For period evidence, choose the displayed category first, then the latest supporting observation, then reader-language preference, then stable occurrence ID. The actual source pair can be FI–SV without English. Exact revision URLs, timestamps, translations and highlights remain in the existing tracker. Source-derived fallback labels must come from selected supporting evidence rather than an unrelated legacy representative.

## Read and search interfaces

- `GET /explore/api/articles?q=...` returns multilingual dataset articles and whether any comparison run is prepared. Listed eligibility does not mean completed history.
- `GET /explore/api/periods?topic=...&languages=...&level=year|month&year=...` returns period state, counts, total and latest assessed month. Add `q` and `search_mode=keyword|hybrid` for a scoped search.
- `GET /explore/api/constellation?topic=...&languages=...&period=YYYY-MM&stamp=...&page=1` returns 100 questions per page, total/pages, category counts, observations and exact tracker links. The frontend fetches all pages in parallel batches of four; there is no discovery cap. `stamp` is optional. `back` preserves the current explorer query.

Question search is keyword first, then locally refined multilingual vector search. Persisted MariaDB full-text documents include accepted question text and selected evidence; semantic retrieval reuses existing passage vectors and a local-files-only query model. Search is scoped to eligible question IDs in the active period and language selection before candidate retrieval. No paid inference or model download occurs while browsing. Missing local semantic capability is labeled keyword fallback.

## Specific question naming

`question_titles.py` creates cached English question labels from bounded representative multilingual evidence. Its structured output identifies the question and supporting source IDs/scope. Deterministic checks and a cached grounding decision accept supported, neutral, specific questions; ambiguous or mixed-topic groups remain provisional/review-needed. Titles cannot introduce facts, imply a winner unsupported by the excerpts, invent contradictions, merge group IDs or replace source quotations. The article and subject/scope must disambiguate questions such as casualties for a particular army.

Generation runs only through the explicitly enabled `question_titles` provider stage, not page loads. Names are cached by article/group/model/policy/evidence identity. Existing rejected/failed reservations are retained. At most two title requests and six total provider requests run concurrently across processes. Titles can be regenerated explicitly after a policy/evidence change; accepted cached labels are reused.

```sh
python -B question_titles.py --topic Q134949 --languages en,fi,sv --workers 2
```

## Dataset rollout

`article_pipeline.py` reuses dataset `article` entities and the existing comparison engine. It supplies article-scoped anchors, histories, run configurations and grouping identities; content embeddings can be shared safely. Existing legacy Winter War runs remain readable. New history preparation uses monthly as-of checkpoints plus bounded recent daily revision checkpoints, rejecting future evidence and deduplicating unchanged revision tuples before repeated comparison work.

The local inventory contains EN 5,254 / FI 19,285 / SV 4,921 editions and 7,256 article IDs represented in at least two languages. Rollout is explicit: finish Winter War, validate a diverse ten-article pilot, then enqueue remaining articles. These inventory counts do not report pipeline completion.

```sh
python -B article_pipeline.py catalog
python -B article_pipeline.py pilot --limit 10
python -B article_pipeline.py prepare --topic Q134949 --languages en,fi,sv --mode history --since 2020-01-01 --workers 6
python -B article_pipeline.py enqueue --pilot --mode snapshot
python -B article_pipeline.py worker --workers 2
python -B article_pipeline.py status
# Only after reviewing the pilot:
python -B article_pipeline.py enqueue --all --mode snapshot
```

The queue is durable and resume is explicit. Browsing never queues acquisition, comparisons or naming. Corpus-wide historical preparation remains an optional explicit job after snapshot pilot validation. The native MediaWiki implementation and independently runnable viewer are separate.

## Verification

Run the scoped AGENTS regression command (111 pure research checks at integration), `node test_skyline_model.js`, `node --check static/lab-explorer.js`, and the independent viewer tests. Zoom-specific checks cover period unions, repeated pairs/passages, selected-pair categories, strongest/latest support, language order, unknown/zero/outside states, exact-date filtering, 215-question pagination, cached/provisional labels, eligibility-scoped search and tracker/back context. Provider tests enforce the narrow naming gate and cached call reuse without network traffic. Root browser acceptance must cover desktop/mobile zoom levels, actual search, daily selector uniqueness, direct historical evidence, keyboard controls and browser Back.

## Integration run status

The nine additional pilot snapshot jobs completed and were read-only smoke-tested alongside the in-progress v2 Winter War historical run. The pilot snapshots contain 88 distinct article-scoped questions in total: Tornedalians 31, Kauko Tuupainen 3, Valvoja 1, Copterline Flight 103 10, Crime and Punishment (1983 film) 3, Erich cabinet 3, 1937 Finnish presidential election 29, Aktiva studentförbundet 3, and Isak Fellman 5. Each has matching persisted search documents. Their common-anchor snapshot dates vary between December 2018 and April 2025; these are not live-current article states or full histories.

With paid calls blocked, every pilot and the v2 Winter War run passed public period/constellation/keyword-search reads, month-blob versus paged-dot reconciliation, language-order invariance, real supporting pair/category/source validation, and an exact archived tracker render. No public read route returned a schema/import failure or 503. The nine snapshot runs were ready; new monthly Winter War preparation and background naming were still running during this check. July's v2 union was 135 questions at that moment and is not a promised final cohort total. The older 324-question/26-checkpoint cohort remains a separate completed legacy run. No whole-corpus processing completion is implied.

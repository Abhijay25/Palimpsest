# NeoWiki judge walkthrough

Open the research app at **http://127.0.0.1:8022/explore**. Enter **Winter War** in the opening prompt, select English, Finnish and Swedish, then open its divergence view. This is a research prototype using archived dataset revisions, not a live mirror of Wikipedia.

1. Start with the monthly histogram across the available history. Red means possible contradiction, amber means different framing, and blue means additional context. Counts are distinct observed questions within the period, not a sum of repeated checkpoints or a truth score.
2. Use the floating zoom controls to narrow or widen the visible date range. For longer histories, buckets may adapt to years; month is the finest scale. Click a bucket to list its questions in an issue table. Each row is one provisional semantic question; repeated passages and language pairs do not add rows. Search and category filters refine the list. A hatched period is unassessed; a missing finding does not prove agreement or resolution.
3. Select an issue row. The source pane shows the actual supporting language pair and assessed date. Compare the original passages, English machine translations, highlights and revision links. FI–SV findings can be reviewed without an English passage.
4. Choose **Open discrepancy tracker** for the Wikipedia-style review screen. The selected run, checkpoint and exact source occurrence travel with you. Browser Back returns to the explorer with its filters and selection.
5. Follow **View original source revision** to inspect the Wikipedia edition, or export the evidence with its provenance. The purpose is to make differences understandable to readers and editors; the visualization does not compose edits.
6. Open the article selector to browse the focused Finnish-history collection. Ready articles are usable immediately. Queued, preparing or failed jobs are labeled; choosing an article never starts paid inference. Most added articles have a single historical snapshot, while Winter War has monthly history.

Optional review flags are stored in this browser. They are not shared editorial decisions or independent citations. Source evidence and its attribution can be exported.

## Useful real starting points

- **Winter War:** search “Mainila” to investigate attribution and accounts of the shelling, or “Soviet” for differing descriptions of Soviet objectives.
- **Lapland War:** “When did the Wehrmacht’s final withdrawal from Finland end?” is an accepted evidence-grounded question. The destruction of settlements also has a Finnish–Swedish finding with no English passage required.
- **History of Finland:** search “Civil War” for the accepted question about deaths and the losing side. Verify population and time scope before treating numbers as incompatible.
- **Svecoman movement:** “What prompted the rise of the Svecoman movement in Finland?” provides a shorter article for a quick comparison.

These are discovered review questions, not verified errors or supplied factual answers. A useful result may be different framing or substantial additional context rather than a contradiction.

## What makes the demonstration real

The pipeline chunks each language independently, uses multilingual passage embeddings with MariaDB vector retrieval to propose counterpart passages, and classifies those pairs with cached Decisions assessments. Related disagreements are grouped into provisional semantic questions. A separate cached naming stage proposes question wording from representative stored evidence and validates grounding. It does not invent a standard question list and then answer it.

Search and navigation reuse stored findings; browsing makes no paid inference calls. Local hybrid search combines keywords with multilingual vectors. The source dataset controls the date cutoff, so differences in this demo must not be described as current Wikipedia discrepancies.

Winter War's completed v2 history has 86 assessed checkpoints, 431 distinct all-time provisional groups and 11,404 supporting occurrences. Its latest checkpoint has 135 groups: 123 additional-context and 12 framing findings, with zero findings passing the strict contradiction gate. These all-time and latest counts have different scopes. The lack of strict contradictions is an actual result, not an empty placeholder.

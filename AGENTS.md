# NeoWiki agent context

## Current hackathon surface

The latest user-approved research journey is prompt-first at bare `/explore`, then a viewport-filling monthly histogram across the available history with a floating toolbar. Zoom changes the date window and adapts to yearly buckets only for longer ranges; month is the finest unit. Clicking a bucket opens a searchable issue table for that period; clicking an issue opens exact evidence. Bucket selection is not zoom. The evidence pane starts closed; selected-question deep links restore it. Earlier constellation and crowded split-inspection layouts below are recorded exploration history, not instructions to restore their default layout.

The user subsequently restored the original Wikipedia styling: white/gray surfaces, blue links/actions, serif headings and familiar sans-serif controls aligned with the article tracker. Preserve the cleaner graph interaction; do not restore the superseded parchment/brown editorial skin.

Month is the finest timeline scale in the main research viewer. Exact checkpoint dates still identify evidence; do not render week/day/minute grids. Preserve alternate experiments and stored historical data.

The user removed the constellation view from this research app. `/explore` always serves the main UI, with no alternate-view link. Older constellation source/read-endpoint names below are historical compatibility, not an exposed viewer. The independently runnable tool in `tools/divergence-explorer` remains a separate PR boundary.

The user explicitly removed Draft edit from the visualization. Its purpose is surfacing and explaining discrepancies to readers and editors, with source Wikipedia links and the existing tracker. Preserve exact occurrence identity through tracker and browser-back links. Optional review markers remain browser-local. Read [the delivery goal](docs/hackathon-goal.txt) and [judge walkthrough](docs/hackathon-walkthrough.md).

The later visualization paths are deliberately PROVISIONAL: the wide popup comparison/diff viewer and link into the article discrepancy tracker work with real stored evidence, but their UX, routing and resolution workflow are not finalized and will change. Do not describe their data as mock fixtures or treat this handoff as the final native MediaWiki integration. Historical observations are not automatically current open issues; a current/resolved status requires a fresh verified check.

Read [the exploration registry](docs/explorations/README.md) before extending a prototype. It records the independent experiments, their source locations, what is actually shipped here, data provenance, validation and unfinished work. Update the registry when adding, retiring or combining an exploration; do not overwrite one experiment's data/status with another's.

## Repository and PR boundaries

- The main branch owns the Finnish/Swedish/English MediaWiki infrastructure and its existing source/local revision reconciliation contracts.
- PR #4 (`feature/divergence-visualization`) adds the independent optional tool under `tools/divergence-explorer`. It does not install a native extension or include the historical inference worker.
- The follow-up `feature/interlanguage-comparisons` branch directly copies the existing working app into `tools/language-gap-explorer`, with source hashes and no implementation rewrite. It is based on PR #4. Keep the PR stacked against `feature/divergence-visualization` while #4 remains open; retarget after it merges.
- The separate `feature/neowiki-review-tools` implementation is an unpublished native extension/worker experiment. Do not silently include its unverified import/recovery work in the standalone tool PRs, modify upstream MediaWiki core, or conflate source revision timestamps with system-versioning processing timestamps.

## Product and evidence rules

Current iteration: `feature/divergence-skyline` changes only the existing research app's `/explore` presentation and historical tracker handoff. It uses EN/FI/SV Winter War data: 324 distinct questions across 26 observations, 3,535 source occurrences and 40 source revisions, through July 29, 2025. Latest observation: 128 questions (116 coverage, 12 framing, zero strict contradictions). Do not confuse this cohort with the older EN/FI/RU standalone sample below. The independent `tools/divergence-explorer` implementation is preserved.

`NEOWIKI_RESEARCH_ROOT` optionally points the research code at an existing ignored data/model/environment root; source/templates still come from this repository. The working skyline preview uses port 8022. No native wiki stack changes are part of this iteration.

The current article edition is always on the left/first, with other editions on the right. Preserve explicit language pair/triplet selection, exact source quotes, revision attribution, cached translations, uncertainty and accessible controls. Missing current-edition evidence requires an honest placeholder.

One historical divergence row represents one provisional underlying semantic disagreement/question, with repeated passages/language pairs attached as occurrences. No fixed topic count, English introduction seeds or assumption of shared article structure. Coverage is passage-level additional information; a retrieval miss is not a whole-article omission. Missing observations are not resolution. Sampled annual spans do not establish persistence. Model probabilities are not truth or a calibrated divergence score.

The real Winter War sample contains 520 provisional tracks / 5,005 occurrences / 26 checkpoints, through July 16, 2025. It found coverage/framing differences, with no pairs passing the strict contradiction gate. Tornedalians snapshot findings have unknown lifetimes. Never replace these conclusions with fabricated examples or describe them as current Wikipedia.

## Runtime, secrets and verification

The packaged viewer defaults to database-free operation. The existing research app explicitly requires its research database/dependencies; use its scoped AGENTS.md and PORT.md. Keep read paths free of preparation/model calls. Any optional inference/enrichment must be explicit, cached, metered and subject to the configured engine policy; preserve failed reservations. Never publish Wikipedia edits, secrets, environment files, local paths or private spending ledgers. Exported Wikipedia excerpts retain CC BY-SA attribution and revision links.

Follow `tools/divergence-explorer/AGENTS.md` for tool-specific checks. Use the existing bounded desktop/mobile verification workflow for UI work. Distinguish fixtures, cached real outputs, live engine reads and a fresh end-to-end pipeline run. Do not restart/rebuild the native wiki stack or weaken its disk guards to test the standalone tool.

The follow-up on the same skyline branch combines a compact count skyline with a virtualized warm heatmap (amber context, orange framing, red possible contradiction). `heatmap.py` reads selected-pair metadata and exact archived cell evidence. Explicit POST search fuses BM25 with local E5 query embeddings and MariaDB cosine search over cached selected-source vectors; model loading is local-files-only. Never invoke Decisions for search, zoom or navigation. Ranking is category priority in displayed observations, not measured controversy, truth or popularity. See the scoped AGENTS.md and skyline guide for the current UI contract.

Current presentation supersedes the crowded heatmap: semantic zoom in `/explore` uses one constellation canvas, monthly blobs and yearly blobs. Periods now count the UNION of distinct observed question IDs, not the previous latest-snapshot rule. One question is counted once across dates/passages/pairs; use the strongest actual selected-pair category in that period. Unassessed/outside periods remain explicit. Question dots link directly to the existing historical article tracker. See `tools/language-gap-explorer/docs/semantic-zoom.md` for the active UI, naming/search pipeline and general-article preparation commands. Structured text generation is now explicitly authorized only for cached evidence-grounded question naming, off the browse path; preserve the narrowly gated provider policy and all request reservations.

Current delivery expands to the judge-ready Finnish-history evidence workflow in docs/hackathon-goal.txt. The constellation is retained at /explore?layout=constellation. Do not revert to the crowded multi-chart interface or add editing tools to the visualization; the latest focus is discrepancy awareness.

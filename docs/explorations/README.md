# NeoWiki exploration registry

## Authenticated on-demand jobs

[Native on-demand jobs](../on-demand-jobs.md) connect permission/CSRF-gated native
request previews to an owned durable queue and isolated background worker. Exact
source/parent hashes and engine versions scope jobs/caches; provider attempts
retain raw responses/usage and failed reservations. Progress, successful-empty,
partial and failure states survive reload. Server spending policy defaults to
disabled and never inherits historical-backfill approval. The public viewer gains
no unauthenticated trigger. The historical campaigns and their queues are separate.

## Language quality and issue context

[Language evidence quality](../../tools/language-gap-explorer/docs/language-quality.md) documents source-bound contextual comments, lazy cached English translations beneath foreign diff paragraphs, exact-witness Decisions question preparation, and conservative offline policy replay. Published source observations and historical identities remain unchanged. Real cached failures and a separate controlled synthetic baseline have regression coverage; independently verified multilingual precision/recall gains are still unestablished. No paid assessment or model training ran for this iteration.

## Native Issues integration (in verification)

The later [Wikipedia-style defaults](../wikipedia-defaults.md) retire the legacy
Blame tab and align supported reading/editor defaults while preserving native
Issues, provenance and explicit inference controls.

The opt-in `infra/wiki/extensions/PalimpsestIssues` extension and independent
signed `tools/language-gap-explorer/native_issues_server.py` now share the unified
index and exact evidence presentation with the previews. Native account review
markers have their own wiki/observation/edition-scoped SVT table; preview markers
are preserved. Source/local reconciliation is checked before exact native article
links/scans. The existing read-only histogram includes all nine detector classes,
separate source-edit/assessment times, sparse coverage states and configured native
period/exact-evidence presets with explorer return context.

Histogram bar handoffs now leave the visualization on its histogram and open
only the article's native Issues list for the selected period. Browser Back and
the article's return link retain the histogram zoom and filters. Older bucket-list
URLs without an exact finding also restore the histogram. Real browser checks
covered both return paths and an old URL; `test_bucket_navigation.js` covers
monthly/yearly routing, filters, history preservation and exact-link compatibility.

This is ongoing implementation/verification, not completion of the native
migration. The previews remain available and the separate NeoWikiReview stack
has not been merged or replaced. The owned FI/SV/EN native runtime now has
reconciled issue-source revisions. Real native browser/API checks cover cached
results, review/undo, exact article links, histogram handoffs and mobile comments.
Pinned official Wikibase Repo/Client, CLDR, Labeled Section Transclusion and
GeoData are installed; 143 captured Wikidata entities reconcile independently in
each edition. Winter War has matching source section/reference/image counts and
no Lua errors; FI/SV normalized text matches, with only romanization-label spacing
different in EN. All article images load in the browser and actual 390-pixel
mobile checks fit each edition. FI/SV Mänttä also match normalized article/citation
text after repairing real coordinate and municipality-code dependencies.
These selected checks do not establish every historical article's fidelity or
user acceptance of native parity.
See [setup, temporal semantics and acceptance record](../native-issues.md) for
the precise boundary and remaining native journeys.

These experiments answer different questions. They share evidence conventions, but their counts, dates, identities and review states are not interchangeable. The existing research app is copied directly into [tools/language-gap-explorer](../../tools/language-gap-explorer/PORT.md). Prototype source paths below refer to that directory. Its source manifest records 82 byte-for-byte copied files; databases, secrets, model caches and reports are excluded. The native extension remains a separate unpublished branch.

## Retired presentations and 3D Library

The current research UI is `tools/language-gap-explorer/templates/lab_explorer.html`, `static/lab-explorer.js` and `static/lab-explorer.css`, with the shared `static/skyline-model.js`. The unused Constellation template and browser assets, earlier skyline/heatmap browser scripts and styles, and copied legacy discrepancy-viewer assets have been removed. `/explore?layout=constellation` continues to serve the current histogram UI. Historical descriptions below record previous iterations, not supported alternate layouts.

The separate `apps/library` spatial bookshelf/corridor app was retired along with its Three.js dependency, isolated setup scripts, tests and `docs/library` implementation documents. Its source and verification history remain in Git. This source cleanup does not delete existing local datasets, models, database volumes or imported article histories.

Shared research code (`skyline.py`, `heatmap.py`, `zoom_read.py` and their read APIs) remains for the current histogram, exact evidence/tracker handoff and compatibility. The independently runnable `tools/divergence-explorer` sample viewer remains supported. `SOURCE_MANIFEST.json` records the original source port, not the current file inventory.

## Map of independent explorations

| Exploration | Question and interaction | Implementation/source | Status and limits |
| --- | --- | --- | --- |
| Snapshot language comparison | What differs between selected article editions? Source-first reviewer page, language pills, highlighted originals and translations. | Prototype `pipeline.py`, `decisions_review.py`, `refine_review.py`, `review_view.py`, `/langcompare/<topic>`. | Real cached Tornedalians findings exist. Earlier hand-authored AI mockups are separate and explicitly labeled; they are not engine results. Snapshot findings do not establish historical lifetimes. |
| Confirmed passage watchlist | If an editor links equivalent passages, which later edits should prompt another review? | Prototype `watchlist.py`, `watch_routes.py`, `/watchlist`. | Persistent relationships, baselines, outcomes and notes. Sandbox/imported revisions demonstrate alerts. This is not live Wikimedia monitoring or automatic edit propagation. Keep sandbox counts outside the real showcase. |
| Tornedalians article/showcase | Can an editor move between a Wikipedia-like article, language comparison and chronological issues? | Prototype `showcase.py`, `showcase_routes.py`, article and showcase templates. | Uses real dataset-era snapshots and a bounded real historical replay. Previously verified 60 source edits, 38 with prose changes and 318 retrieved counterpart matches; those are replay metrics, not contradiction counts. |
| Chronological update issues | Which local or foreign semantic edits deserve review for the current edition? | Prototype `update_issues.py`, `/wiki/<topic>/updates` and issue details. | Other-Language Edit / Local Edit origin pills; small exact diffs, full Wikipedia diff links, edition-scoped review outcomes. Deterministic value/negation/size rules select candidates; an issue is not itself a Decisions-confirmed error. Foreign references appear only for a relevant foreign edit. |
| Winter War edit-event timeline | What meaningful edits occurred in each edition? | Prototype `semantic_timeline.py`, `timeline_routes.py`, timeline templates. | Cache contains 200 real revisions across EN/FI/SV/RU and 151 assessed changed units. Edit-change labels are not cross-language contradiction judgments. Counterpart retrieval respects event-time and dataset-anchor cutoffs. |
| Reference-led historical comparison | Can a small source-led seed set be followed over revisions? | Prototype `historical_divergence.py`, earlier v1–v4 runs. | Superseded discovery experiment. Its six English-reference groups were rejected because they restricted topics and assumed structure. Retained storage/schedule helpers are useful; do not present its six-row result as the symmetric engine. |
| Symmetric semantic divergence engine | What distinct underlying disagreements recur across passages, languages and time? | Prototype `paired_history.py`; shared paragraph/vector/revision helpers. | Independently chunk all selected editions; MariaDB cosine top-3 both ways; parallel Decisions relationship predicates; variable-size same-disagreement grouping. Real replay: 26 checkpoints, 741 distinct actionable pairs, 5,005 occurrences and 520 provisional tracks. Three unavailable cached assessments remain excluded without provider retries. No strict contradictions detected in this run. Grouping is provisional, not exhaustive atomic claim extraction. |
| Full-viewport divergence viewer | How does the number and type of semantic disagreements evolve over time? | [Standalone tool](../../tools/divergence-explorer/README.md), [PR #4](https://github.com/Abhijay25/Palimpsest/pull/4), commit `6a667fd`. | Shipped in #4 with a real compressed public sample and optional local engine adapter. Prompt-first topic/language input, one row per provisional question, occurrence drill-down and day-limited zoom. Earlier hand-authored timeline fixtures are not included as real data. |
| Native MediaWiki review tools | Can article tabs, revision hooks, jobs, accounts and persistent review state use MediaWiki's existing entities? | Separate local `feature/neowiki-review-tools` implementation, commit `bf2efbd`; `infra/wiki/extensions/NeoWikiReview`, `infra/review/worker`. | Unpublished extension/worker experiment. Uses native revisions/jobs/accounts and derived MariaDB VECTOR/SVT tables. Earlier native synthetic-save, CSRF, source deletion and SVT restore checks passed; final recovery/native reruns and the real Tornedalians import remain incomplete. Not included in #4. |
| Inter-language comparison follow-up | Bring the existing comparison workspace and engine into this repository unchanged. | `feature/interlanguage-comparisons`, stacked on #4. | Direct source port under `tools/language-gap-explorer`; includes the existing comparison page, snapshot engine, temporal engine, watchlist and update/timeline experiments. PR #4 files remain unchanged. No reviewer/engine rewrite is included. |
| Historical revision flags tab | Review explicit detector suggestions for current-edition revisions in a selected skyline block. | `tools/language-gap-explorer/flags_tab.py`, `/article/<topic>?tab=flags`. | Optional standalone UI port of the native flags interaction. GET reads only cached audits; scans are explicit, cached, and unavailable text is reported rather than rendered as an empty diff. The offline Q-demo fixture is synthetic, not Wikipedia evidence. |

## Data and semantic distinctions

### Current skyline iteration

`feature/divergence-skyline` implements the approved first complete reader flow in the existing research app: article/language prompt → aggregated skyline → paginated questions → the article's existing discrepancy tracker. All three EN/FI/SV pairings participate; repeated occurrences and pairings count once per underlying question. Columns use the latest assessed observation in a calendar period, with unknown gaps and day-limited zoom. The selected run, observation, question and actual source pair survive the handoff and browser-back navigation. Full historical evidence appears in the existing Wikipedia-style tracker shell, not a second reviewer implementation.

The EN/FI/SV Winter War preparation completed 26 checkpoints from January 1, 2020 through July 29, 2025: 324 distinct provisional questions, 3,535 source occurrences and 40 source revisions. The latest checkpoint contains 128 questions (116 coverage, 12 framing, zero strict contradictions). These counts differ from the earlier EN/FI/RU cohort. Every stored quote offset, source timestamp and language-anchor cutoff was audited. No provider requests were made by overview, question-list, tracker or browser navigation checks; source translation continues through the existing local translation path.

Verification: 52 research tests plus 15 independent-viewer tests pass; calendar aggregation checks cover latest-not-sum, unknown-versus-zero and responsive binning. Browser checks covered desktop/mobile, FI–SV evidence without an English passage, English-left EN–SV evidence, local translation, keyboard selection, category/observation restoration, and a one-day zoom limit. The independent viewer and native wiki stack remain separate. This is presentation/context routing over the existing engine, not a new clustering pipeline or an accuracy claim.

The supplied FineWiki/MariaDB research corpus contains August-2025-era multilingual snapshots; it is not live Wikipedia and does not include complete original histories. The main infrastructure's acquisition/import pipeline preserves original article/revision IDs and reconciles them to local wiki IDs. Do not assume source IDs equal local IDs.

The prepared Winter War common comparison window is January 1, 2020 through July 16, 2025, using six annual observations plus 20 recent cached edit checkpoints. Annual gaps are unobserved. Historical rendered HTML may contain newer transclusions. An analysis-run timestamp, a source-edit timestamp and a system-versioning processing timestamp mean different things.

Vector nearest neighbours produce candidate passage pairs, not confirmed identity or disagreement. Decisions relationship checks and same-underlying-disagreement checks are separate steps. Repeated mentions belong under one provisional semantic track. Fixed representatives reduce transitive merging, but candidate limits and paragraphs containing multiple claims can still cause duplicate or overly broad groups. Row counts depend on languages, chunking, source coverage, thresholds and grouping.

Snapshot comparison, update issues, confirmed watchlist relationships, local edit labels and historical disagreement tracks must retain separate IDs and state. Reviewing an EN issue must not silently review FI's issue; a browser-local review marker must not be described as a persisted database outcome. A model label is not verified fact, author intent, sentiment, national bias or reliability.

## Shared implementation conventions

- Current edition left/first; counterparts right; mobile preserves that order. Original quotes and source links remain authoritative.
- Use searchable language pills for pairs/triplets. Scope results and labels to actual selected occurrence pairs; another edition's contradiction cannot leak into a selected pair.
- Prefer complete eligible prose from each selected edition. Avoid English lead seeds, six-topic caps, presumed parallel headings and forced matches.
- GETs read cached data. Acquisition, embedding, inference and enrichment are explicit operations. Overview rendering and source detail loading have separate paths; translations/highlights do not block an overview.
- Missing retrieval is unknown, not omission. Missing phases are unknown, not resolution. Discrete relationship categories guide review; do not manufacture a continuous severity score or colorful conflicts.
- Do not publish Wikipedia edits. Keep credentials, local paths, private ledgers and model downloads out of Git. Public exports keep exact revision attribution and CC BY-SA notices.

## Validation record and next work

PR #4's 15 tests and GitHub CI passed. Its browser check covered the real 520-track graph, a track with four occurrences, current-left evidence, mobile layout, a one-day zoom limit and no captured console errors. Optional engine reads were tested against the prepared prototype; forwarded enrichment was mocked. These checks do not certify a fresh end-to-end historical inference run from this repository.

See [tool verification](../../tools/divergence-explorer/verification.md) for the precise standalone boundary. The separate native branch's recovery/import work needs its own acceptance checks. Future additions should record their commands, source anchors, data scope, output counts, whether calls were mocked/cached/live, and unresolved limitations here and in their scoped `AGENTS.md`.

## Searchable heatmap follow-up

The skyline branch now layers a compact count overview over a virtualized heatmap in the existing research app. Warm discrete category colors and borderless adjacent cells preserve the visual bands while keeping unassessed gaps explicit. Search, pair/category filters, observed category-change filtering and an explained strongest-category ranking help readers navigate hundreds of questions. The unchanged EN/FI/SV cohort has 324 all-time questions; 313 appear in the initial latest-per-year observations. Exact cell evidence opens the existing historical article tracker with preserved navigation context.

The explicit search action fuses keyword BM25 with local E5 query embeddings and MariaDB cosine retrieval over existing selected representative source vectors. It makes no Decisions calls and cannot download a model; keyword fallback is labeled. Semantic candidates are bounded for relevance search, while ordinary question discovery remains uncapped. No new historical checkpoints, inferred lifetimes, controversy scores or native MediaWiki features were added. Validation: 61 research + 15 independent-viewer Python checks, JS model/syntax checks, and desktop/mobile live cached-data journeys including search, FI–SV evidence, monthly/day zoom, browser Back, keyboard arrows and virtualized scrolling through all 313 initially represented questions.

## Current semantic zoom and general-article preparation

The user rejected showing a histogram, heatmap and evidence sidebar together on a laptop. The active research presentation now uses one constellation canvas: a month's distinct questions as equal-size dots; zoom out to monthly blobs and yearly blobs. Period totals are a union of semantic IDs across observed dates and selected pairs, with each ID's strongest supported category. Monthly dots reconcile with the month blob; monthly totals are not additive into years. Search stays collapsed, keyword first and local hybrid second. Evidence opens the existing historical article tracker directly, preserving run, actual supporting occurrence and return context.

Specific question naming is an explicit cached background pipeline rather than fabricated UI summaries. A tightly limited generative stage proposes neutral source-grounded questions and validates evidence IDs/scope with cached grounding decisions. Missing or rejected labels remain provisional. New persisted keyword documents and existing MariaDB vectors support search. Browsing makes no provider calls; the only new generative authorization is background question naming.

General preparation now accepts article-scoped edition anchors, cache/run/group identities, monthly as-of history samples and bounded recent daily checkpoints. A durable MariaDB queue supports two article workers and shared provider concurrency limits. The current corpus contains 7,256 eligible multilingual IDs; this is an eligibility inventory, not a claim of completed assessment. Rollout is Winter War, then a ten-article pilot, then an explicit remaining-corpus queue. Existing legacy cohorts remain readable. See [semantic zoom guide](../../tools/language-gap-explorer/docs/semantic-zoom.md). The 111 pure research regression checks plus JS syntax/model checks passed during integration; browser acceptance is recorded by the root agent after the current run. Native integration and the independent viewer remain untouched.

Live integration record: the nine additional pilot snapshot jobs completed with 88 article-scoped questions and matching search documents. All nine plus the in-progress v2 Winter War history passed read-only public API and archived tracker smoke checks with paid calls blocked. Their source-anchor dates vary honestly between 2018 and 2025. New monthly Winter War preparation and naming were still running during this check; do not describe those jobs or the remaining 7,256-article inventory as complete. Detailed counts and the distinction from the completed legacy run are in the semantic zoom guide.

## Supplied editorial matrix and hackathon delivery

The user supplied an editorial matrix/split-inspection reference and requested a simple, foolproof working MVP. /explore now uses this layout, with self-hosted Newsreader/Inter, actual category counts, period-union temporal strips, scoped keyword/hybrid search, exact archived evidence and local translations/review/export. The constellation is preserved at layout=constellation. Basic date-header/Space-drag panning and Reset avoid additional chart layers.

The original real-data backfill is complete: Winter War v2 has86/86 checkpoints,431all-time groups and11404occurrences; latest135(123context12framing0strictcontradictions). The initial ten-article pilot has519groups and11498occurrences. Audit checked22996excerpts across192revisions with0offset/anchor violations. This remains distinct from older v1/RU runs. The expanded20-article Finnish-history/editor-draft delivery is specified in ../hackathon-goal.txt; queued articles are not described as already prepared.

## Prompt-first overview and discrepancy awareness

The latest approved interface restores Wikipedia's white/gray/blue styling and centered article/language entry prompt, and makes the graph the main viewport. A floating toolbar navigates one level at a time: aggregate years, selected-year months, then a selected month's questions. Month is the finest timeline unit. Overview counts are period unions of actual question identities and strongest selected-pair categories; they are not repeated-observation sums or inferred continuous persistence. Selecting a finding opens exact evidence; source Wikipedia and existing tracker links remain available. The older constellation stays independently accessible.

A local Draft edit experiment was implemented during this iteration and explicitly removed before delivery at the user's request. The final visualization focuses on discrepancy awareness and evidence for readers/editors. Exact historical occurrence identity survives tracker navigation, including weaker findings within a stronger aggregate group. Source export remains attributable; there are no editing controls in the visualization.

Focused Finnish-history preparation now exposes ready/partial/queued/paused/failed state through a read-only collection endpoint. Successful cached work can be published when other requests are unavailable; unknown assessments and deferred grouping stay explicit. Browsing neither retries failed paid reservations nor queues preparation. The detailed objective and judge script are in [hackathon goal](../hackathon-goal.txt) and [walkthrough](../hackathon-walkthrough.md).

Final data preparation: the curated 20 EN/FI/SV articles all have published findings (18 ready, 2 partial), with 1,301 latest-observation and 1,597 all-time article-scoped questions. The two partial runs retain 1,632 unavailable candidate assessments; no failed reservation was resent. The provenance audit checked 12,645 occurrences / 25,290 excerpts / 227 source revisions with zero invalid offsets, identities, URLs or cutoff violations. This validates provenance, not factual correctness: the single possible-contradiction flag appears to be a model false positive and is documented with source links. Conflicting classifier signals are exposed in evidence rather than silently relabeling stored findings. See [data status](../hackathon-data-status.txt).

Final user navigation replaces the prior click-year/month hierarchy: default monthly histogram over the full available history, zoom changes its date window and adapts to yearly buckets for longer ranges, clicking a bucket opens a searchable issue table, then selecting an issue opens evidence. Month is the finest timeline unit; the issue table has no large colored temporal bands. The latest presentation uses Wikipedia's white/gray/blue style and has no draft-editing controls.

The popup comparison viewer and subsequent article-tracker navigation are intentionally provisional UX, backed by real cached evidence rather than fabricated examples. Their design/routing and the distinction between historical observations and current actionable issues will be iterated later; no finalized native MediaWiki lifecycle is implied.

## Unified article preview

The reader (`/wiki/<topic>`), snapshot/historical comparison (`/langcompare/<topic>`) and detector interface now share `article_shell.html` and one Article / Language differences / Flags navigation bar. `/article/<topic>?tab=article|language|flags` exposes the combined preview; existing routes remain compatible. Tab links retain repeated language selections, run, question, observation, exact occurrence, return context and selected detector revision. Changing revision in Flags updates the tab destinations. Opening a view does not trigger a detector scan, including old `scan=1` links.

The Article view reads the existing dataset snapshot. For a historical evidence selection it shows exact archived excerpts and original revision links rather than substituting the snapshot. If a selected detector revision differs from the snapshot, the reader labels the difference. Full historical article rendering in this preview is not implemented. Snapshot language findings and historical findings keep their separate data scopes. Flags remain detector suggestions; unavailable cached audits are explicit.

This is a consolidation of the Flask preview, not a native MediaWiki integration. Native wiki core remains in its pinned Docker image, with PalimpsestBlame and PalimpsestFlags extensions under `infra/wiki/extensions`; their code and databases are unchanged.

### Flags runtime and anchored comments

The preview launcher (`scripts/preview.py`) starts the detector and reader together using one private environment file. Detector health gates scan controls; cached audits remain readable. Failed detector responses cannot become successful cache entries, transport errors are presented without internal addresses, and revision changes clear stale evidence. Gemini structured results use JSON Schema with local Pydantic validation. Whole-page consistency has a bounded configurable deadline, rather than the earlier eight-second cutoff. Windows rendering can reuse installed Edge/Chrome.

Revision comments share the native MediaWiki extension's stacking implementation: desktop cards follow their exact source marks, with collision handling; narrow screens use inline markers and anchored popovers. Real verification on Winter War revision 1301539037 returned three detector suggestions and a successful whole-page consistency response with zero suggestions (about 11 seconds). Those are model results, not verified errors or an accuracy evaluation. Cached browser checks covered Scan, page consistency, source highlights and comment placement on desktop/mobile, with no browser script errors. Original source text and histories were preserved.

## Unified Issues and SVT follow-up

Article / Issues replaces the three-tab preview. The list combines stored language discrepancies and detector flags, but defaults to one latest assessed set: newest indexed historical run at its newest published checkpoint, plus newest assessed source revision per detector mode/edition. History retains older runs and observations. Winter War's initial index contains 1,275 language-group identities across three different cohorts (431, 324 and 520) plus three detector flags; the default correctly shows 135 findings from the latest language checkpoint plus those three flags (138), not their all-time union. Counts are provisional findings, not verified factual errors.

The MariaDB `unified_issue`, `unified_coverage` and `unified_review` tables use system versioning. `unified_assessment` and `unified_observation` are append-only successful evidence records. System time does not replace source-edit, observation or assessment timestamps. Explicit backfill imports successful paired-history, snapshot and detector results without inference. Language observations pin their original paired-occurrence payload with a hash. Detector results are archived before their working cache is replaced, with a private pending-result recovery file if indexing fails.

Review markers persist per exact observation and article edition; they are shared within this localhost prototype. They do not establish confirmation, dismissal, current presence or resolution. Full-page evidence uses the Flags highlight/comment renderer with distinct edition, edit and within-revision comparison modes. Historical and weaker-occurrence links preserve their identity and explorer return state. Failed or missing evidence never falls back to a different occurrence/current snapshot.

This remains an interim Flask surface. The required destination is a native MediaWiki article Issues tab and evidence workflow, using native revision lookup, accounts, permissions and navigation. The pinned upstream core and separate native extension experiments remain untouched; source Wikipedia IDs must be reconciled rather than assumed equal to local revision IDs.

Verification: 187 research regression tests passed (one opt-in database check skipped in the pure run); that database check also passed separately against uniquely named temporary tables, including immutable rescans, idempotence, empty assessed sets and SVT histories. The separate divergence viewer's 15 tests passed. Real backfill imported 21,248 historical language occurrences, 533 snapshot records and nine successful flag-cache assessments without inference; repeating an import left the total 21,789 observations unchanged. These import counts describe source records, not distinct issues. Browser checks covered persisted review/undo, desktop and mobile anchored comments, and exact histogram-to-evidence navigation with restored explorer state.

The next user-approved goal is native MediaWiki delivery with complete, correctly rendered article content and all preview Flags behavior carried over. Do not delete the previews until the user explicitly verifies native parity. Expand the history histogram to include all detector classifications with distinguishable colors and type filters; navigation into native Issues must preset the selected period, languages, classifications and exact historical evidence, then restore the explorer on Back. Keep paid scans explicit and preserve source/local revision identity.

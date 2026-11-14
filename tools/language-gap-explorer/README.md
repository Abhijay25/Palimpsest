# Wikipedia Language Gap Explorer

Current integrated flow: [article/language prompt → monthly histogram → issue table → exact evidence](docs/semantic-zoom.md), using the prepared EN/FI/SV research cohort. The obsolete research constellation UI and its source assets are removed; existing period and paginated-question APIs remain available. The original comparison, watchlist and timeline experiments remain available.

Local Wikipedia-style reading and comparison app. The full supplied snapshot has 29,460 articles; 7,256 linked topics have multiple language editions. Start Docker Desktop, run `./start.ps1`, and open http://127.0.0.1:8010. The app and database bind to localhost. Review progress is at `/reviews`.

## Fast Decisions-only pipeline

The current engine is `paragraph-v2-k3-decisions-only-v1`. It makes **only Decisions API calls**. The provider rejects any generation endpoint. The earlier extraction/explanation pipeline is retired; its stored results remain historical.

Local multilingual E5-small embeddings are cached. Paragraph/sentence chunks target 280 model tokens, cap at 400 and retain exact snapshot offsets. Markdown tables and reference sections are excluded from prose matching. Within each Wikidata topic, MariaDB retrieves three nearest passages per other language, including adjacent context. This avoids global Wikipedia comparisons.

Four evidence groups are batched per request. Decisions classifies relations, estimates a factual-conflict predicate and selects source/target sentence IDs from fixed choices. Source text is never regenerated. Warning highlights require all of: conflict classification, confidence at least 0.5, conflict predicate at least 0.8 and valid selected source sentences. Only those sentences receive highlights. Different coverage remains unmarked; equivalent information is omitted. Verdicts are model judgments, not verified facts.

Classification uses no generated explanations. Finnish and Swedish evidence now has a separate local English translation, clearly labeled as machine translation. Review criteria and editor notes are templates. Existing mock examples remain explicitly labeled via `?demo=1`.

Benchmark: Tornedalians completed 40 evidence groups in 20.6 seconds, with prepared embeddings, using ten batched requests. No comparison passed the conflict threshold in that run. Future times depend on article length, local preparation and API latency. The original synthetic calibration is not evidence of real-world accuracy; bilingual review remains needed.

## Reader and reviewer flow

Open an article, then **Compare languages**. Select two available editions or all three. Pair views show only evidence within the selected pair; triplets combine existing pairwise results rather than claiming a joint three-way verdict. Selection uses cached results and incurs no API calls.

The default view shows conflict flags only, grouped by article section. Exact evidence and highlights appear upfront; review criteria and tools are collapsible. Other coverage and inconclusive judgments are available through filters. These are navigation groups, not semantic deduplication or guaranteed unique editorial issues. Comparison review status is saved in the browser; the new update watchlist below persists reviews in MariaDB. No edits are published.

## Processing and budget

The existing ignored `.env` is read privately, accepting `OPENAI_API_KEY` or the workspace's existing `OPEN_API_KEY` alias. Never paste credentials into chat. No new key was created.

`start.ps1` starts the database and local app. It no longer starts a paid comparison worker automatically. **Run review** explicitly queues work; run `pipeline.py --watch` separately to process queued comparisons. Reads never make paid AI calls. A single worker lock prevents duplicate processing, while a global budget lock enforces the shared $10 pilot ceiling. Successful requests are cached, and failed/unknown calls retain reservations. Costs are conservative metered estimates, not invoices. The original and new pilot share this same ceiling.

```powershell
# Queue the approved ten-topic pilot, without immediate calls
.venv/Scripts/python.exe pipeline.py --pilot --queue-only
# Process a selected topic
.venv/Scripts/python.exe pipeline.py --topic Q2606233 --once
# Process queued reviews in the background
.venv/Scripts/python.exe pipeline.py --watch
# Local-only full-corpus embeddings; potentially lengthy
.venv/Scripts/python.exe pipeline.py --embed-all
# Full multilingual run, gated by controlled evaluation; NOT auto-launched
.venv/Scripts/python.exe pipeline.py --all
# Export progress and real evidence for human review
.venv/Scripts/python.exe report_pipeline.py
# Current regression and reader-UI checks
.venv/Scripts/python.exe -m unittest test_decisions_only test_pipeline
.venv/Scripts/python.exe check_reader_ui.py
```

The live pilot is ten topics, not all Wikipedia. Failed runs require explicit resumption. The full paid corpus run is not launched automatically. A MediaWiki fork and automatic editing remain outside this version.

## Revision-driven language update watchlist

Open http://127.0.0.1:8010/watchlist. The existing demo was committed on `main` as `8cdd8de`; this feature lives on `feature/cross-language-watchlist`.

1. Use **Watch related passages** in a comparison, or **Link passages** on the watchlist. Choose a source language and an exact excerpt.
2. Explicitly search for counterparts. Cached local multilingual E5 embeddings and MariaDB cosine search retrieve up to three passages per other language within the same topic. Similarity suggests candidates; it does not establish that two claims mean the same thing. The candidate index currently covers the original snapshot; changed imported passages can be absent until that index is refreshed.
3. Confirm one counterpart per language (pairs or triplets), give the relationship a useful title, and record what has been checked. The app saves the exact passages and their revision IDs as a baseline.
4. Open the link and use **Try a local edit**. Saving a sandbox revision runs deterministic diff detection. Changes to either linked passage create a review notice; unchanged passages, relocated passages and whitespace-only changes do not. Ambiguous or removed anchors are flagged for link review.
5. Review the original before/after diff beside the counterpart and its English translation. **Already covered** or **No update needed** records a new baseline; **Update needed** keeps the notice open. **Stop watching** deactivates the link. Every outcome has a persistent reviewer note. Newer changes supersede older unresolved notices without deleting their history.

The core update path uses **zero paid model calls**. An explicit **Optional AI check** can ask Decisions whether the edit changes a factual assertion and affects the counterpart. Its scores never approve edits or advance the baseline. This separates cheap change detection from the existing Decisions discrepancy classifier.

The seeded Tornedalians example changes **1888 → 1889 only in a local sandbox revision**. It is not a real Wikipedia correction, and the seeded link is labeled as a demonstration baseline. Original article snapshots are immutable. The watchlist stores separate documents, revisions, links, notices and review events in MariaDB.

This MVP supports sandbox edits and full-text revision imports, **not a live Wikimedia edit subscription**. To import a revision, create a UTF-8 JSON file with `topic`, `lang`, `text` (the complete new article), `base_revision` (the current local revision ID shown in the UI), and optional `upstream_id` and `label`, then run:

```powershell
.venv/Scripts/python.exe watchlist.py --ingest-json revision.json
```

Imports reject stale base revisions instead of overwriting newer work. Upstream IDs are retained as provenance. There is no automatic cross-language propagation or Wikipedia publishing.

## Local English translations

Finnish and Swedish excerpts are translated with official Argos model packages, run through CTranslate2 on the CPU with int8 weights. No translation API key or paid generation call is used. Exact originals remain visible; names and phrasing can be imperfect, so the translation is a review aid rather than evidence. Model downloads require network access once; inference works offline.

`setup.ps1` installs the dependencies and models and seeds the demonstration. For an existing installation:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
.venv/Scripts/python.exe local_translation.py --install
.venv/Scripts/python.exe watchlist.py --seed-demo
./start.ps1
```

The app initializes tables on startup. Translation starts lazily for visible excerpts and is cached in MariaDB by source text and model version. Model packages and provenance are stored in ignored `model-cache/translation/`. A missing model produces a retryable message while keeping the original text readable.

Verification (requires the local database and installed translation models; browser checks also require the app):

```powershell
.venv/Scripts/python.exe -m unittest test_watchlist test_decisions_only test_pipeline
.venv/Scripts/python.exe check_watchlist_ui.py
.venv/Scripts/python.exe check_reader_ui.py
```

## Attribution

Wikipedia text and derived vectors: Wikipedia contributors, CC BY-SA 4.0, via FineWiki and MariaDB Foundation release `s-2026-10`. Revision links preserve attribution/history. Adaptations must retain attribution and share-alike terms. The three original MariaDB repositories are alongside this app; their code and the E5 model/export have their respective MIT licenses.

## Focused discrepancy highlighting and upfront evidence

The language control is now a searchable multiselect with removable pills and keyboard navigation. Source excerpts are visible immediately; only review criteria and editing controls are collapsed. Headers derive from highlighted factual numbers where available, otherwise original source text, rather than generic model packet names.

High broad conflict predicates are no longer silently discarded because an independent category or sentence selector disagrees. `refine_review.py` runs a focused follow-up: select relevant sentences, check whether their factual differences warrant review, test equivalent claims, then batch token-membership predicates only for qualifying pairs. Refused token judgments remain unhighlighted. Highlight offsets refer to exact original text and are HTML escaped. Classification remains Decisions-only; English translation runs separately with local models.

The pipeline distinguishes a logical contradiction from an apparent discrepancy needing clarification. In particular, 1999/2000 recognition language can refer to different legal milestones. A highlight never establishes which edition is true. Per-word checks are limited to flagged sentence pairs, not the entire corpus. The extra refinement means the earlier 20.6-second base benchmark does not include the optional focused highlighting pass.

## Tornedalians showcase

Article, Compare languages and Update tracker share a Wikipedia-style workspace at `/wiki/Q2606233?lang=en`. Reading and comparison use the supplied August 2025 snapshots. Historical replay is separate from the sandbox watchlist; simulated edits are excluded from showcase counts.

Prepare the one-topic showcase with `.venv/Scripts/python.exe showcase.py --prepare --history-limit 20 --run-review`.

Imports at most 20 actual edits per language ending at each dataset revision. Public metadata and rendered revisions are cached in ignored `data/showcase-history/`. Both diff sides use identical prose extraction. Counterpart revisions are capped at the edit timestamp and their dataset revision, preventing future-text leakage. MariaDB retrieves three candidates per other language, showing the best with alternatives expandable. Relationships are inferred, not editor-confirmed agreement.

The Update tracker has Needs review and All edits/history views, five edits per page. Outcomes and reviewer notes persist in MariaDB. An optional Decisions check shares the existing $10 budget. Reading, replay and local translations make no paid calls. Run analysis explicitly starts a bounded background worker with progress polling; completed runs reuse their existing results.

`reports/tornedalians-showcase.json` records settings, revision IDs, findings, history coverage, elapsed preparation time and the global API ledger. Failed imports remain explicitly incomplete and resume with the same command. Real-world accuracy requires human assessment; replay alone does not establish accuracy. No Wikipedia edits are published.

Additional checks: `.venv/Scripts/python.exe -m unittest test_showcase`.

Live browser integration: `.venv/Scripts/python.exe check_showcase_live.py`. Offline layout-only checks: `.venv/Scripts/python.exe check_showcase_ui.py`. The latter does not replace database/worker integration tests.


Update tracker revision: article-edition-specific issues, not an all-language evidence feed. `/wiki/Q2606233/updates?lang=en` lists chronological issues with open/reviewed, cross-language/local and newest/oldest filters. Each row represents one historical edit with qualifying changed passages. `/wiki/Q2606233/updates/<event_id>?lang=en` opens compact escaped diffs and the full Wikipedia diff link. Only foreign edits with a retrieved counterpart in the target edition show language references; local edits show no foreign passages. Rules select value/negation/substantial wording changes; cross-language candidates additionally allow at least three changed tokens. These are explicit heuristics, not Decisions semantic verification or confirmed errors. Formatting/punctuation and small wording changes are excluded. `showcase_issue_review` is append-only and scoped by event + target language; reviewing for EN must not close the FI issue. Legacy event-level reviews are preserved separately. Browser reads make no paid calls. Tests: `test_update_issues` plus the existing suite; `check_showcase_live.py` now exercises the issues table/detail navigation. `check_showcase_ui.py` remains layout-only.
# Winter War semantic timeline experiment

Branch: `feature/winter-war-semantic-timeline`. Open `/wiki/Q134949?lang=en` and choose **Semantic timeline**, or visit `/wiki/Q134949/timeline?lang=en`.

The bounded replay uses the 50 revisions ending at each dataset anchor in EN/FI/SV. Russian is resolved from the Q134949 Wikidata sitelink and pinned at or before the English anchor. It stays separate from the original corpus. Exact normalized prose and section-heading changes receive overlapping Decisions labels for facts, framing and added/removed information; wording, inconclusive results, missing revisions and unassessed passages are explicit. Labels are candidates for human review, not verified contradictions or judgments about editors.

```powershell
# Optional resumable acquisition while MariaDB is unavailable; no paid calls.
.venv/Scripts/python.exe -B semantic_timeline.py --fetch-only --limit 50
# Import cached/real revisions and explicitly assess them, using the EXISTING shared $10 ledger.
.venv/Scripts/python.exe -B semantic_timeline.py --prepare --classify --limit 50
# Idempotent resume/report; reading the page never starts preparation or assessment.
.venv/Scripts/python.exe -B semantic_timeline.py
.venv/Scripts/python.exe -B -c "from local_translation import install_models; install_models()"
.venv/Scripts/python.exe -B -m unittest test_semantic_timeline test_showcase test_update_issues test_decisions_only
.venv/Scripts/python.exe -B check_timeline_ui.py
```

`check_timeline_ui.py` is an isolated offline browser contract/layout check using synthetic fixtures. It does not prove a completed live backtest. Actual preparation exports ignored `reports/winter-war-timeline.json`; acquisition checkpoints are in `data/winter-war-timeline/manifest.json`.

**Compare editions at this time** is an explicit CSRF-protected POST. It selects a counterpart revision at/before the event and target anchor, then ranks three candidates using local multilingual E5-small embeddings and MariaDB exact cosine search restricted to that revision. This is candidate retrieval, not a cross-language contradiction judgment. Your edition remains left; the changed edition is right. No extra paid call is made. Original before/after text and local Argos translations remain visible.

Limits: historical sample, not live Wikipedia; different edition windows are not comparable bias rates. Normalization excludes tables/infoboxes and reference lists. Historical HTML is rendered today, so templates/transclusions may reflect newer versions. Long changed passages are bounded to 1,200 characters and 400 tokenizer tokens per side and may lose alignment/context; those splits are labeled. Meanings require both semantic-change and category scores at least 0.80. Scores are not calibrated factual correctness probabilities. No automatic Wikipedia edits. Preparation, tables and caches are isolated from Tornedalians results and review history.

## Article flags tab

`/article/<topic>` combines the existing Language comparison with an explicit Flags tab for the selected skyline block. Cached audits are read on GET; scanning is deliberate and posts to `PALIMPSEST_API_URL` (default `http://127.0.0.1:8765`) with a 90-second timeout. Revision and audit cache files live under `data/flags-cache/` (or `LANGGAP_FLAGS_CACHE`), which is ignored.

For a database-free UI check, set `LANGGAP_FIXTURES=1` and run `python -m flask --app app run --host 127.0.0.1 --port 8022`; open `/article/Q-demo?tab=flags`. The synthetic fixture includes no Wikipedia text and never makes a network or detector request unless an uncached scan is explicitly requested.

# Library verification

Verified runnable revision: **`65a1e057f7c1676496f23ff30d950bea84b793a6`**, branch `feature/library`. Main application implementation is `997829c1326c7c8f958eb321a8a48fc12c0d8cdb`; later commits add passing guard tests and correct a catalog language announcement. Coherent Blame baseline: `74fa014f63b50669925d8a0bd964d5383f8038af`. Later handoff changes are documentation only. No push, PR or public deployment was performed.

Implementation started **2026-11-14 10:21:26 UTC** with a hard deadline of **13:21:26 UTC**. The final functional checkpoint after preview verification was **12:45:43 UTC**, elapsed **2 h 24 min 17 s**, including interruptions. Only documentation handoff followed. Work stayed within the original three-hour cap.

The localhost app is **http://127.0.0.1:5180/**. Read [setup and operation](../../apps/library/README.md) for reproducible commands and [continuation work](future-work.md) for remaining requirements versus optional expansion.

## Actual corpus and runtime

All nine articles have original public histories through their locked S source anchors, imported content hashes/parents reconciled to local revisions and installed verified provenance bundles. C5 reports `complete=true`, no article-history failures and **133** reconciled revisions. Rendering is a separate report and remains incomplete.

| Topic / Wikidata | English revisions; local/source anchor | Finnish revisions; local/source anchor | Swedish revisions; local/source anchor |
| --- | --- | --- | --- |
| Luntoberget / Q110908561 | 10; 37 / 1236860974 | 8; 67 / 22491167 | 12; 23 / 56176496 |
| Krejansberget / Q110908692 | 14; 27 / 1302147010 | 9; 76 / 22491166 | 10; 33 / 56176492 |
| Round Tower (Vyborg) / Q4241896 | 11; 13 / 1254266029 | 49; 59 / 22513700 | 10; 11 / 55143451 |
| Language totals | **35** | **66** | **32** |

Source-anchor timestamps (UTC):

| Topic | English | Finnish | Swedish |
| --- | --- | --- | --- |
| Luntoberget | 2024-07-26 22:48:04 | 2024-07-04 04:12:45 | 2024-11-06 15:19:41 |
| Krejansberget | 2025-07-23 17:15:54 | 2024-07-04 04:11:57 | 2024-11-06 15:19:28 |
| Round Tower | 2024-10-30 05:23:16 | 2024-07-15 19:06:08 | 2024-07-03 05:22:10 |

Tested on macOS 27.0 with Node 22.23.3, Python 3, React 19.3.1, TypeScript 7.0.2, Three.js r187 and Vite 8.3.8. MediaWiki **1.46.2** and MariaDB **11.8.9** use the exact digests in `infra/wiki/images.lock.json`. Browser automation uses the pinned Playwright Python **1.65.1** image; the existing local tag was `palimpsest-blame-browser:1.65.1`, with its entrypoint explicitly overridden to the mounted Library test. The README provides a separate reproducible Library image tag from the same pinned Dockerfile.

Ollama **0.9.6**, bge-m3 F16 / 566.70M, 1024 dimensions; local model digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`. Article vectors are the SHA-256-verified S precomputed bge-m3 assets aligned with the displayed source anchors. The S release does not pin the exact upstream model-weight revision/preprocessing digest; numerical identity with the local GGUF weights is not claimed. Actual query compatibility was tested by frozen semantic relevance expectations.

Feature-owned ports: MediaWiki fi/sv/en **48181/48182/48183**, vector DB **48184**, Ollama **11435**, app **5180**. Private state is under ignored `.local/library/`. Existing default wikis **8081–8083**, Blame wikis **48081–48083** and auxiliary services **8001/8002** all returned HTTP 200 afterward. The old fictional prototype had no listener at its documented **5173** during the handoff check; its unchanged source was restarted there and returned HTTP 200. Only that workspace's requested AGENTS lessons were edited; its app code was preserved.

## Requirement evidence

| ID | Status | Observed evidence and limits |
| --- | --- | --- |
| L01 | Delivered; fresh-machine run unverified | Separate app, feature-owned services, all preparation phases exercised on this host, documented setup and preserved parent services. No final clean-machine rehearsal. |
| L02 | Passed | 3 Wikidata books × fi/sv/en; 133 original revisions; C5 reconciliation and provenance checks; all nine live native analyses ready. |
| L03 | Passed | Real Ollama embedding → native MariaDB cosine vector query. Three frozen relevance cases passed. Actual model and DB shutdowns separately returned 503 without results, then recovered to the correct tower topic. |
| L04 | Passed for this corpus | Vector-derived multilingual mean-distance projection, three actual labeled books, guided transition and native UI semantic search navigation. Layout deliberately requires exactly three topics. |
| L05 | Passed for imported history | Native wheel input advances new-to-old; 49-edition corridor reaches its oldest original revision through windows of at most 28 objects. Unit oracle checks 705 unique alternating slots and deterministic tied timestamps. |
| L06 | Delivered with rendering limits | Full exact-edition article document, selectable mapped text and paused camera. Some generated citations/templates remain incomplete; source text has not been replaced with a fabricated preview. |
| L07 | Passed focused native cases | Actual mouse drag across the frozen Finnish mixed-revision phrase, exact word groups/colors, matching selection timeline and inline paragraph placement; native partial Unicode selection and keyboard Enter inspection. |
| L08 | Passed focused guards; broader replay unverified | Native consumer/producer reused unchanged. Actual generated text is refused without a partial request; over-limit selection returns its exact native reason; stale language responses cannot replace the current edition. Unknown topic/language/revision/proxy guards pass. Hidden/privacy and ambiguous move/revert cases were not replayed end to end through this standalone host. |
| L09 | Passed | Historical English Luntoberget r34 → latest imported Swedish r23, announced 6 Nov 2024, old panels removed; Finnish reset also observed. Browser tower language reset passes. |
| L10 | Passed focused routes | Exact paused/restored camera and focus; local r11 versus original source r325335 links; invalid/missing/de language links expose usable recovery without opening a substitute edition. |
| L11 | Passed desktop/fallback scope | Keyboard route, 390×844 reduced-motion catalog/reader without overflow, actual WebGL context-loss fallback, native desktop walking benchmark above 30 FPS target. Physical mobile text-selection handles unverified. |
| L12 | Delivered | Baseline/tested SHA, actual commands/results, elapsed checkpoint, private evidence, limitations and prioritized continuation estimates recorded. |

## Checks and observations

`npm test`: **5/5 passed**. Ordinary provenance fixture validated before checksum/language negatives; tied chronology and duplicate rejection; 705 alternating slots; vector-layout relation; multilingual identity grouping. These are structural/domain checks, not proof of live integration.

`npm run build`: **passed**, TypeScript plus production Vite build. JavaScript bundle approximately 788 kB / 212 kB gzip. Python setup/extraction/browser scripts compiled successfully in memory.

`npm run verify:live`: **passed again after restarting the committed server**. All nine real histories and analyses were ready with verified complete article provenance. Three frozen relevance queries passed: Vyborg tower 1547–1550 → Round Tower; Bronze Age Siuntio mounds → Luntoberget/Krejansberget; Finnish paraphrase → the same burial-site topic identities. Five route/proxy guards passed; four further input/origin checks passed. Initial model load took 23.5 seconds, then approximately 0.1–0.8 seconds for warm queries; recovery after process restart took 2.5 seconds on this host. These are observations for nine vectors, not scale benchmarks.

`tests/browser_acceptance.py`: **7 cases passed, no page errors**, using real endpoints and native mouse/keyboard actions. The frozen quote is **“Torni rakennettiin vuosina 1547–1550”**, source UTF-16 range **311..347** in Finnish Round Tower. Original word-owner revisions were audited before comparison: **325335, 330197, 331279, 17859948, 22513700**, mapped locally to **11, 26, 27, 51, 59**. Selected whitespace has an additional owner; it is not manufactured into a visible word group. The timeline is checked separately against the native selection-event contract. At least three distinct colors and article/group color equality were asserted. No programmatic range substituted for this mouse selection.

`tests/spatial_acceptance.py`: **passed**, real Chromium ANGLE SwiftShader WebGL. Checks guided keyboard entry, real forward wheel input, 49 editions across bounded windows, actual reader pause, exact camera/focus restoration, separate source/local links and an actual `WEBGL_lose_context` event followed by the same usable list. Software rendering is only functional evidence and is not credited as a performance pass.

`tests/guard_acceptance.py`: **passed, no page errors**. An ordinary real Finnish passage is validated before 65 valid ranges return `selection-range-limit-exceeded`, without source text or partial selection data. An actual transcluded `Template:Cite web` selection shows the native zero-verified-offset refusal, no revision groups, and no new analyze request (two before, two after). This mappedness check uses a browser Range over real content; native gesture coverage remains the separate mouse suite. A real Swedish 12-revision response is delayed and released unchanged after switching to Finnish; the reader stays on Finnish r67 and its 4 Jul 2024 date.

After the final catalog-only language announcement correction, the production build and guard suite passed again. Backend integration and scene geometry were unchanged, so their already passing checks were not repeated.

The unchanged native PHP regression runner also **passed 27 isolated attribution, DSR, selection, date-bound and link fixtures** in the exact locked MediaWiki image, with a read-only repository mount and no network. This supports preserved native semantics; it does not substitute for the outstanding live privacy/ambiguity replay through the new host.

Native in-app browser: observed the lattice, two topic corridors, an English historical Luntoberget edition, inline Blame and cross-language discovery/reset. A real partial drag selected **“yör”** inside **“Pyöreä”** at source start 79. Oldest Finnish tower reader r11 returned to exactly **`[0, 1.8, -120]`** in the settled native run.

Final native desktop performance: **4,073 frames / 79.149 active seconds = 51.46 FPS average**, 1280×720, warm renderer, middle → oldest → newest camera transitions. Active editions remained at most 28; newest-window draw calls were 309. This average includes settled and moving portions and is not a frame-time percentile or a multi-device guarantee. Earlier concurrent software-browser testing reduced native throughput; no cross-machine or long-duration soak claim is made.

Repairs discovered by real checks: focusable word spans collapsed Chromium cross-span selections, so the adapter temporarily removes and restores their keyboard attributes during pointer selection; tests verify restored attributes and keyboard activation. Invalid-link recovery initially sat below catalog content and now receives actual clicks above it. Language-control identity, first-frame timing and label density were also corrected. Production CSP remained intact; browser wait predicates were corrected instead of weakening it.

## Evidence and remaining limits

Private reproducible outputs live in `.local/library/evidence/`: `native.json`, `browser.json`, `spatial-browser.json`, `reader-guards.json`, `selection-limit.json`, `dependency-outages.json`, `request-guards.json`, `unicode-selection.json`, `camera-restoration.json`, `walking-performance-final.json`, `discovery-journey.json`, `model.json`, `preserved-services.json`, and desktop/mobile PNGs including the final catalog/reader. Logs are under `.local/library/`; C3/C4/C5 and provenance are under `.local/library/wiki/`. No credentials, model files, database contents or large downloads are committed.

Template/module closure remains **incomplete**: the bounded support pass acquired ten supporting pages and preserved rate-limited pending dependencies. Some citation/infobox/generated output is missing or unmappable. Original article-history completeness does not certify rendering completeness. The new reader preserves native attribution refusals. No entire-Wikipedia inventory, generated RAG answer, semantic drift, true infinite inventory, public hosting or production readiness is claimed. A broader native negative matrix and clean-machine reproduction remain outstanding, with estimates in `future-work.md`.

| Changed files | Reason |
| --- | --- |
| `apps/library/src/`, `public/` | Spatial lattice/corridor, responsive book reader and accessible fallback |
| `apps/library/server/` | Verified corpus, real search, constrained native API/reader adapter |
| `apps/library/scripts/`, `compose.yaml`, `corpus.json` | Reproducible isolated runtime, original histories, provenance and vectors |
| `apps/library/tests/` | Domain invariants and actual native reader/spatial acceptance |
| `apps/library/package*.json`, build configuration | Pinned app dependencies and localhost build/development workflow |
| `PRODUCT.md`, `DESIGN.md`, `docs/library/`, READMEs | Approved scope, implementation contract, evidence and continuation work |
| `.gitignore` | Exclude generated builds and design-seed output |

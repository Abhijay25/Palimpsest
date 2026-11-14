# Autonomous session log — 2026-11-14 (09:00 → ~12:30 +08)

You were away. These are the decisions I made on your behalf, and the questions I parked for you. Each is marked **[review]** when I think you should check it.

## Decisions made

### Bias detector
- **Refs are attributed to the sentence they sit after**, not the whole paragraph. A changed sentence with no citation of its own is marked `uncited`: it gets no Exa call and is judged on framing only. *Why:* real case `en_revert` "Dominic Zvada" added a November claim whose paragraph refs were all about April.
- **Exa hard cap of 400 calls per `prepare`** (`EXA_MAX_CALLS`, about $0.40). Calls are cached, so re-runs cost nothing. Your budget: $5–10, with $15 as the absolute ceiling. The running spend is tracked in the progress log below.
- **Prompt stage2_v2 is the default for real-edit runs.** It beat v1 on the synthetic sets: 0% versus 5% clean edits flagged.
- **More clean controls** (EN 30, FI 20). *Why:* with 7 controls, a single wrong flag swings the false-positive rate by 14 points, so your 5% bar couldn't be measured.

### Stealth scanner (`stealth_ai_poisoning_dom_scanner_spec.md`)
- Built as the subpackage `palimpsest/stealth/`, not a single `stealth_scanner.py`, to match the existing package layout.
- **Edit-relative scanning**: for a diff, only hidden channels that are *new* in the edit are reported. Pre-existing comments and collapsed navboxes are not the editor's doing. This is the same lesson as the bias detector's r02 false positive.
- **Homoglyphs**: only words that *mix* scripts are flagged. A whole Cyrillic word (a legitimate transliteration, which is common in Finnish history articles) is not.
- **Pillar 2 (triage of hidden text)**: Haiku stands in for `gemini-decision-1`, using the same two-phase file exchange as the bias judge.
- **Pillar 3 (screenshot OCR vs DOM): deferred. [review]** It needs Playwright plus a vision model. Claude can read images, so it is buildable, but it is the costliest piece and the least likely to matter for wikitext diffs.
- **Ref pages via Exa are extracted text, not raw HTML. [review]** CSS-hidden lures on a cited page may already be stripped by Exa, or may be included as plain text. Either way, Pillar 1's CSS checks can't see them. Unicode and instruction-phrase checks still run on the Exa text. A raw-HTML fetch of each ref (free, but a direct request to third-party sites) would close the gap; I parked it for you.

## Questions parked for you
1. **Silent source** (r03 `en_spec_05`): if the cited source neither supports nor contradicts a changed fact, should that be flagged as citation hijacking (your spec's G1), or should it abstain and fetch more text (your spec's Case 5)? See `eval/runs/r03/findings.md`.
2. Should Pillar 3 be built with Claude vision as the stand-in, or wait for Gemini?
3. Should the scanner fetch raw HTML of `<ref>` pages directly, in addition to Exa?

## Progress log
(appended as runs complete)
- **09:10 r04** — first real edits (Finnish, v2 prompt): Sonnet flagged 2/20 clean controls (10%, over the bar). Cause: a silent source was treated as a contradiction, and Exa returned stub windows. → `eval/runs/r04/findings.md`
- **09:12** — Stage 1 now drops stub and off-topic windows; prompt **stage2_v3** adds the silent-source rule (G1 needs a contradiction; unsupported *motives* are still G3). **This answers parked question 1 the conservative way. [review]**
- **09:15 r05s** — v3 regression check on 45 synthetic cases: recall 100%, 0 false alarms, exact label 44/45 (Haiku) and 43/45 (Sonnet), up from 42/42. Spec Case 5 is now correct.
- **09:19 r05fi** — v3 on the real Finnish edits: **0/20 false alarms for both models**, escalations down from 4–6 to 0–2. The clear POV insertions are still caught. Mainila: the "reverted" edit is literally supported by its YLE citation, so it is correctly passed. → `eval/runs/r05fi/findings.md`
- Exa spend so far: ~$0.03.
- **09:22** — the stealth pre-hook is wired into the bias pipeline. Diff and ref-page text are sanitised before Stage 0 and the judge, and a CRITICAL ref page never reaches the judge. Disabling sanitisation makes 2 tests fail. Pillar 1 on all 32 real wikitext diffs and 15 cached ref pages: 0 false alarms.
- **09:30 s01** — stealth eval (69 cases): 87% accuracy, 2.6% false alarms, 16.7% misses. All misses are Pillar 1 regex gaps. → `eval/stealth/runs/s01/findings.md`
- **09:36 s02** — after the fixes: seen sets near-perfect, 0/42 false alarms on real Wikipedia. **Held-out attack recall 8/12 (67%)**: regex CSS rules don't generalise. One held-out case is contaminated (noted). → `eval/stealth/runs/s02/findings.md`
- **09:40** — replacing the regex CSS list with a property-based inline-style visibility model. A second held-out set is being written blind. **[review]** A rendering-based T_human (MediaWiki parse → headless browser) is the robust long-term answer; I recommend it as the Pillar 3 build.
- **09:42 s03** — stealth with the inline-style visibility model: **blind held-out attack recall 12/13 (92%), 0/7 held-out false alarms, 0/37 false alarms on real Wikipedia.** Pillar 2 triage now adds 4 catches over Pillar 1. Stopped tuning on held-out cases to avoid contamination. → `eval/stealth/runs/s03/findings.md`
- **09:44 r06en** — v3 on the 20 real English edits: clear POV insertions caught by both models ("beautiful, breathtaking", "weird", "best player to never win", "almost universally condemned… civilized societies", "highly addictive"). Misses: a loaded-label swap ("illegal" → "undocumented") and a selective deletion of sourced content. → `eval/runs/r06en/findings.md`
- **09:50 r07** — prompt **stage2_v4** (loaded labels + selective deletion) over all 97 cases: the label and deletion cases are caught; clean edits flagged Haiku 4%, Sonnet 2%; planted recall 22/22.
- **09:53** — confidence-tiered routing (≥0.70 admin queue, 0.45–0.70 review queue). r07 admin-queue false alarms: Haiku 2%, Sonnet 0%. **[review]** The thresholds are a product decision, and they must be re-fit on Gemini's calibrated scores.
- Exa spend so far: ~$0.09.
- **09:55–10:15** — Gemini API backend (`prepare --backend gemini`, google-genai 3.3.0, no CVEs; the Decisions API endpoint is a marked TODO). FastAPI `POST /api/v1/audit-diff`, `POST /api/v1/stealth-scan`, `GET /healthz`, smoke-tested on a live server. A whole-package code review found 7 issues; 6 were fixed (judge failures now count in recall, ref-attribution fallback, untrusted-field delimiters with prompt **stage2_v5**, a per-request Exa budget, bounded template scanning that flags truncation, span offsets mapped back to the raw text) and 1 was documented as intended (a poisoned ref page routes to admin without an editor penalty).
- **10:16 r08en** — ~~held-out~~ (**correction 14:35: 6 of the 14 reverts were also in the r06en tuning set; on the 8 truly new reverts Sonnet flagged 5, Haiku 6**) set of 44 new real English edits: Sonnet caught every revert containing visible POV wording (9/14; the rest are vandalism or neutral changes). Admin-queue false alarms on 30 controls: Sonnet 1 (3.3%), Haiku 2 (6.7%).
- *(usage limit hit ~10:20; resumed 12:31)*
- **12:36 r09ctl** — 46 more controls. **Combined 76 English controls, admin-queue false alarms: Sonnet 2.6%, Haiku 5.3%.** Most flagged "clean" edits are real citation mismatches that survived patrol (e.g. a sentence changed 2→3 years against its AP source, the Tito constitution 1963→1974 against its source).
- **Total Exa spend: ~$0.22** (of the $5–10 budget).

## Where things stand
| Component | Status | Best number |
|---|---|---|
| Bias detector (stage2_v5, Sonnet judge) | working end-to-end on real edits | admin false alarms 2.6% on 76 real EN controls; POV-worded reverts caught (but 6/14 r08en reverts overlapped tuning data, see correction) |
| Stealth scanner (Pillar 1 + Haiku triage) | working, wired before Stage 0 and on ref pages | blind held-out attack recall 92%, 0 false alarms on 42 real hidden-markup edits |
| API | `/api/v1/audit-diff`, `/api/v1/stealth-scan`, `/healthz` | stealth works now; audit-diff needs `GEMINI_API_KEY` |
| Gemini swap | `prepare --backend gemini` + API auto-detects the key | untested against the live API |

## Questions for you (summary)
1. Thresholds: admin ≥ 0.70, review 0.45–0.70. Keep them? They need re-fitting on Gemini's calibrated scores.
2. Haiku-class as the cheap first pass and Sonnet/Hydrogen-class for the admin queue?
3. Pillar 3 (render-based visibility via MediaWiki parse + headless browser): build it, or wait for Gemini?
4. Raw-HTML fetch of ref pages (in addition to Exa text) to catch CSS-hidden lures on cited sites?
5. Split "possible manipulation" from "citation mismatch / likely update" in the admin queue (r09ctl findings)?
6. API `lang_code` is limited to en/fi (Stage 0 word lists exist only for those); Teammate 1 needs de/fr/es.

---

# Session 2 — 2026-11-14 14:30 → (user away again)

User decisions (14:08): thresholds re-fit on Gemini only; Haiku first pass, Hydrogen expected better; Pillar 3 = headless-browser screenshots in viewport-sized tiles (no separate page download); ref pages: Exa text feeds the judge while a raw-HTML scan runs concurrently and can escalate; split "manipulation" vs "citation mismatch" only if accurate; en/fi first, **no hard-coded language or test tricks anywhere**.

## Audit for test-specific tricks (14:30)
- **Leak:** stage2_v4/v5 used `"illegal" <-> "undocumented"` as an example — the exact r06en miss. Fixed in **stage2_v6** (example removed; the general WP:LABEL rule stays). r07's catch of that case does not count.
- **Held-out overlap:** 6/14 r08en reverts were also in the r06en tuning set (the builder was not given the r06en files in `--exclude`). A fresh set `en_reverts3`/`en_controls3` is being built with every earlier case file excluded.
- **Stealth phrase detector:** English-only and includes our own schema words (`CLEAN_PASS`, `audit_status`) that my synthetic attacks also use. To be made language-neutral.
- **Stage 0 word lists:** not a trick — they add reasons but any non-typo change reaches the judge anyway. They are why the API only accepts en/fi; to be relaxed.

## Progress log
- **14:35 stage2_v6** — leaked example removed; default prompt. **r10v6:** the leaked "illegal → undocumented" case is still caught by the general WP:LABEL rule (Haiku 0.75, Sonnet 0.65). → `eval/runs/r10v6/findings.md`
- **14:41 s05ml** — language-neutral injection screening (added prose and prose template params go to triage; zero-width split words in any Latin/Greek/Cyrillic language). Blind fi/de/fr/sv set: **misses 4/21 → 0/21**, 0 false alarms on 42 real edits. → `eval/stealth/runs/s05ml/findings.md`
- **14:50 Pillar 3 (p02)** — system Chromium, viewport tiles with 64 px overlap, deterministic visibility model + triage: **16/16 blind attacks, 0/10 benign pages, 1/37 real cited pages flagged** (a paywall overlay). Vision layer (Haiku): 4/4 image-text attacks but 4/8 real pages flagged → vision does not escalate on its own. SSRF guard on every request. **[review]** DNS-rebinding/redirect/WebSocket gaps remain → production needs an egress firewall around the renderer. → `eval/stealth/runs/p02/findings.md`
- **15:00** — audit-diff runs the cited-page render scan concurrently with the judge (only escalates, never blocks); any Wikipedia language code accepted (no watch list → language-neutral rules only); `.env` has an empty `GEMINI_API_KEY=` entry and Gemini is never used unless `PALIMPSEST_USE_GEMINI=1`.
- **15:10 efficiency** — screenshots only when vision needs them: real-page render p50 2.4 s → 1.6 s, no PNGs on disk. Judge prompt ~1.8k tokens + ~0.4k per case.
- **15:15 reasons** — intent ("manipulation" vs "update") cannot be read reliably from a diff: of 8 flagged *clean* controls, 2 were real POV, 2 citation mismatches, 2 likely updates, 2 unsupported motives. Instead each flag gets a descriptive reason code (CONTRADICTS_SOURCE / UNSUPPORTED_CLAIM / LOADED_WORDING / REMOVED_CONTEXT) from verdict + diff, zero extra tokens; 19/20 agreement with my labels on a 20-case dev set. **[review]** labels are mine.
- **15:20 r11fi (blind Finnish, uniform sampling)** — Sonnet: 11/20 reverts flagged, **0/30 controls**; Haiku: 7/20, 2/30 admin (6.7%). → `eval/runs/r11fi/findings.md`
- **15:20 latency** — edits are split into changed paragraphs and judged 4 at a time (cap 12, then `partial`). With a 1.5 s judge: 1–3 changed paragraphs 1.8 s, 5–8 3.6 s, 12+ 5.5 s ceiling; our overhead ~70 ms. Sources per unit fetched concurrently.
- **15:25 stage2_v7 (default)** — WP:BLP exception to the silent-source rule: added damaging claims about identifiable people/organisations need explicit support. Blind BLP set: contentious unsourced claims caught **1/12 → 12/12** (both models), neutral additions 0/12 flagged. Real controls: the rule's only new admin flags (1 Sonnet, 1 Haiku) are both real BLP problems patrol missed ("convicted" vs source "charged"; an unsourced violence claim). → `eval/runs/r12v7ctl/findings.md`
- **15:28 variance [review]** — with no prompt change, single-run admin counts on 71 controls move by about ±2 (cases cross 0.70 both ways). Comparisons between prompt versions need repeat runs; Gemini at temperature 0 should reduce this.
- **15:30 cascade (offline, from existing runs, zero cost)** — Haiku first pass, Sonnet only when Haiku flags: same admin precision as Sonnet alone (7/222 clean edits = 3.2%), **84% of Sonnet's revert catches (16/19) at 20% of Sonnet's calls**. Recovering the last 3 needs 67% of calls (Haiku's low-confidence passes are common). This is the cost/recall dial for the Haiku → Hydrogen setup.

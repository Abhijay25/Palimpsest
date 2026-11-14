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

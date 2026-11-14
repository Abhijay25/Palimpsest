# s05ml — language-neutral injection screening (2026-11-14 14:41)

Change (commit 69e7938): Pillar 1 no longer relies on English phrases alone.
- Added visible prose in a diff (>= 4 words) is sent to Pillar 2 triage as one screen item; it escalates only if triage says `is_prompt_injection`, otherwise it is dropped (no status change).
- Prose template parameters (>= 8 words, any language) are screened the same way and stay in the human text.
- Zero-width characters splitting >= 2 words of Latin/Greek/Cyrillic script go to triage (one stray ZWSP is a common line-break hint and is ignored).

| Set | s04ml baseline (Haiku triage) | s05ml |
|---|---|---|
| attacks_multilingual (blind, fi/de/fr/sv, 32) | 26/32, **4/21 attacks missed** | 30/32, **0/21 missed** |
| attacks_heldout2 (blind, 20) | — | 17/20 (errors are CLEAN vs BENIGN_NOTES only) |
| benign_real_en + benign_real_fi (42 real edits) | — | 36/42 exact, **0 false alarms** |
| all 94 | — | false alarms 0, misses 0, Pillar 1 alone 70% |

Remaining exact-label errors are all non-alarm (BENIGN_NOTES_ONLY vs CLEAN), plus two real Finnish homoglyph vandalism edits now reported as CSS_CLOAKING (triage called the token narrative cloaking) instead of HOMOGLYPH_SPOOFING — still flagged.
Caveat: the multilingual set was written by a Sonnet subagent that never saw the scanner; it is small (14 injections). Cost: one extra triage item per edit with added prose (production: one Gemini decision call).

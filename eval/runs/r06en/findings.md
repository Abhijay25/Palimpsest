# r06en — REAL English edits (the 10 reverts + 10 controls from the first builder), prompt stage2_v3

Exa: 45 calls, $0.037. Sources: 17/20 ok (English refs are far more available than Finnish).
These cases predate the ref-to-sentence fix, so Stage 1 tries up to 3 paragraph refs and keeps the best-matching window.

## Reverts (10) — both models flagged 5, Sonnet one more
| Case | Both flagged | What the edit did |
|---|---|---|
| en_revert_1385526185 | G2 | added "beautiful, breathtaking" |
| en_revert_1385499242 | G2 | added "weird" |
| en_revert_1385458319 | G2 | "the best player to never win finally won" |
| en_revert_1385369001 | G2 | "almost universally condemned and considered immoral in civilized societies" |
| en_revert_1384842438 | G2 | "It is highly addictive." (Haiku confidence 0.55) |
| en_revert_1385505593 | Sonnet G3 / Haiku pass | "waived … after missing multiple field goals" read as an implied cause (Zvada; the cited sources are about April and August) |

Not flagged:
- **en_revert_1385523558** ("illegal" → "undocumented"). The reverter cited WP:NPOV. **Miss**: the rubric has no loaded-label rule.
- **en_revert_1385380193**, a likely conflict-of-interest account, **deletes** the sentence saying organisations supported a sentenced activist and linked her prosecution to her human-rights work. **Miss**: the rubric doesn't judge deletions. This is the second deletion case, after `fi_revert_19464447`.
- en_revert_1385379830 ("completed a master's degree" → "graduated"), en_revert_1385441363 (an unsourced family-prominence sentence): arguably fine to pass.

## Controls (10)
- 1 flagged by both models: `en_control_1384172251`, "The AP projected that X will advance" → "X advanced" (edit summary "past tense"; the source is an AP live-results page). The flag is defensible under G2 (projection stated as fact), but it is a good-faith update. **Counted as a false alarm: 1/10.**
- Haiku abstained on 1 (paywall stub).

## Change → stage2_v4
Two rules added: loaded labels and euphemisms (WP:LABEL) → G2; selective deletion of source-supported content that shifts balance → G2 (or G1 if the meaning reverses).
v4 has to be validated on cases it was *not* tuned on: the new English builder output and the synthetic regression set.

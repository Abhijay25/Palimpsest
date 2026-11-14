# r07 — stage2_v4 (loaded labels + selective deletion) over all 97 existing cases

Cases: 45 synthetic/spec (regression), 32 real Finnish, 20 real English. Exa: 31 retry calls, $0.006.

| | Haiku v3 → v4 | Sonnet v3 → v4 |
|---|---|---|
| Clean edits flagged (50 clean controls + synthetic clean) | 1 → **2 (4%)** | 1 → **1 (2%)** |
| Planted violations caught (22) | 22 → 22 | 22 → 22 |
| Real reverts flagged (22) | 7 → 10 | 8 → 11 |

New catches (the edits v4 targeted):
- `en_revert_1385523558` "illegal" → "undocumented": both models (G2, conf 0.80 / 0.85).
- `en_revert_1385380193`, the COI deletion of sourced support/criticism: Haiku G2 (0.50).
- `fi_revert_19464447` removes "as a fascist organisation": Sonnet G2 (0.55).
- Also `fi_revert_23392352` (Sonnet, 0.55) and `en_revert_1385505593` (Haiku now agrees with Sonnet's G3).

New false alarm: `fi_control_15327239` (Haiku G2, 0.50). A good-faith rewrite of the Malmi Airport section removed an outdated "future is uncertain" sentence. **The source was unavailable**, so the deletion rule's own condition ("the window supports the removed content") couldn't be met, and Haiku flagged it anyway.

## Confidence-tiered routing [review — product decision]
Flags made without an available source all sit at confidence ≤ 0.60. With **≥ 0.70 → admin queue, 0.45–0.70 → patroller review queue**:
- Admin-queue false alarms: Haiku 1/50 (2%, the AP "projected" → "advanced" case at 0.75), Sonnet 0/50.
- Real POV reverts still reaching the admin queue: "beautiful, breathtaking", "weird", "the best player to never win", "illegal → undocumented", "almost universally condemned … civilized societies", "highly addictive" (Sonnet), the Swedish great-power insertion (Sonnet).
- Deletion catches and silent-source catches land in the review queue. That is appropriate for lower-certainty signals.

Note: confidences are the model's self-report, not calibrated probabilities. The Gemini Decisions API is supposed to return calibrated scores, so the thresholds must be re-fit on that backend.

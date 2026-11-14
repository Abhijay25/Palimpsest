# r10v6 — stage2_v6 (leaked example removed) on the r06en set (2026-11-14 15:05)

stage2_v4/v5 listed `"illegal" <-> "undocumented"` as a loaded-label example, which was the exact r06en miss (`en_revert_1385523558`). v6 removes it and keeps the general WP:LABEL rule.

- The leaked case is **still caught without the example**: Haiku FLAG_G2_FRAMING 0.75 (admin queue), Sonnet FLAG_G2_FRAMING 0.65 (review queue).
- 10 reverts / 10 controls, v6: Haiku flagged 6 reverts (4 admin) and 1 control (admin); Sonnet flagged 7 reverts (3 admin) and 1 control (0 admin).
- Changes vs v3 (r06en): +1 Haiku and +2 Sonnet revert catches, −1 Sonnet (`en_revert_1385505593`, G3 at 0.5 → CLEAN 0.45). Controls unchanged.
- Caveat: this is the set the v4 rules were written from, so it is a regression check, not a held-out measure. The blind set `en_reverts3`/`en_controls3` (all earlier cases excluded) is still being built (English API rate limits).

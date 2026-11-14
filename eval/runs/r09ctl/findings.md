# r09ctl — 46 more surviving English edits (clean-control assumption), prompt stage2_v5

Exa: 47 calls, $0.043. 2 cleared at Stage 0.

| | Admin queue (conf ≥ 0.70) | Review queue | Any flag |
|---|---|---|---|
| Haiku | 2 / 46 | 4 | 6 (13%) |
| Sonnet | **1 / 46** | 4 | 5 (11%) |

**Combined with r08en (76 English controls):** admin-queue false alarms are **Sonnet 2/76 (2.6%)** and Haiku 4/76 (5.3%); any-flag rate is Sonnet 7/76 (9.2%).

## The flagged "clean" edits are mostly real citation mismatches
- `en_control_1384191447` (Wander Franco): "two-year" → "three-year" suspended sentence. Both models G1 at 0.9. **The cited AP source says two years.** The editor pasted a bare ESPN URL about an appeals ruling into the text instead of adding a `<ref>`, so this is probably a good-faith update that the citation doesn't support.
- `en_control_1384193048` (Yugoslavia): the president-for-life constitution moved to 1974. **The cited History.com source says 7 April 1963.**
- `en_control_1384192494`: "scientist" → "mad scientist" in Wikipedia's voice (review queue).
- `en_control_1384190873`: peacock "talented" (Sonnet, review queue).
- Two hedge/qualifier removals ("tentatively", "Although technically defeated") and one attribution removal (review queue).

"Survived" ≠ "clean": the detector is finding real WP:V/NPOV gaps that patrollers let through. For an admin tool, these are useful, but they are **citation-maintenance** signals, not manipulation signals.

## Suggested next step [review]
Split the admin output into "possible manipulation" and "citation mismatch / likely update". A cheap deterministic signal: the edit adds a new URL or `<ref>` that the old text lacked, so a G1 contradiction against the *old* ref is probably an update → route to review, not admin. The Wander Franco case would move to review.

# r11fi — blind Finnish set, stage2_v6 (2026-11-14 15:20)

Set: `fi_blind_reverts` (20) + `fi_blind_controls` (30) from dataset M, seed 2026, **every earlier Finnish case excluded** and **no POV-regex preference** (reverts sampled uniformly; earlier sets preferred regex matches, which inflates recall). Never seen by any prompt revision.

| Model | Reverts flagged (admin ≥0.70) | Controls flagged (admin) | EXPAND |
|---|---|---|---|
| Haiku | 7/20 (4) | 4/30 (**2 = 6.7%**) | 3 |
| Sonnet | 11/20 (9) | 0/30 (**0%**) | 0 |

Sources: of 20 reverts, 9 had a usable window, 6 were uncited changes, 5 unavailable; controls 16 ok / 13 unavailable.

What Sonnet passed (9 reverts): typo-vandalism (out of scope), neutral facts the cited source does not mention (passed by design), one height change 411 → 486 m against an "ok" window (possible miss, needs a reader), an unsourced family-relation claim about a living person.

**Silent-source rule re-checked (analysis only, no prompt change):** CLEAN_PASS edits that add an ACTION_FACT the window does not support occur in 67% (20/30, Sonnet) of blind Finnish controls and 57–78% of English controls — the same rate as in reverts. Surfacing "unsupported addition" would flag most clean edits, so silence stays a pass.

Gap (Haiku's own note): contentious unsourced claims about living people (e.g. a KGB allegation) pass under the silence rule unless the wording is loaded. WP:BLP treats these as high-priority; candidate for a narrowly scoped exception, to be measured on fresh data.

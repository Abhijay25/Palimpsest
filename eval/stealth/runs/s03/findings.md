# s03 — inline-style visibility model + attribute-text channel; Haiku triage only (Haiku and Sonnet triage were identical in s01/s02)

| Bucket | n | Attacks | Caught | Pillar 1 alone caught | False alarms |
|---|---|---|---|---|---|
| spec | 7 | 6 | 6 | 6 | 0 |
| evasion (seen) | 20 | 19 | 19 | 18 | 1 (`evasion-16`, see s02) |
| held-out 1 (misses described to the fixer in the abstract) | 18 | 12 | 11 | 7 | 0 |
| **held-out 2 (fully blind)** | 20 | 13 | **12 (92%)** | 8 | **0/7** |
| real benign FI + EN | 42 | 5 real homoglyph vandalisms | 5 | 5 | **0/37** |

- From s02 to s03, blind held-out recall rose from 67% (held-out 1 in s02) to 92% (held-out 2 in s03), with no new false alarms on real markup.
- **Pillar 2 now carries weight**: on the blind set, Pillar 1 surfaced 8/13 as flags and triage lifted it to 12/13. The attribute-text and visible-instruction channels send candidates to triage instead of deciding deterministically.
- Remaining misses (both template parameters): an instruction in an infobox `|alt=` param (`heldout2-03`) and in a citation `|quote=` (`heldout-07`). Pillar 1 doesn't surface them, because media params are only read inside `[[File:…]]` and template-param text needs strong imperative phrasing to count. A simple fix is to surface *any* added template-param text of ≥4 words to triage. **Not applied:** tuning on held-out misses would contaminate the sets again, so I stopped here.
- Latency: Pillar 1 p50 0.31 ms, p95 1.3 ms (spec target <5 ms ✓).
- 0 invalid triage lines across 81 items.

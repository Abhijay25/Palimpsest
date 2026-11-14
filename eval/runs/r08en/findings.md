# r08en — HELD-OUT test: 44 new real English edits (14 POV reverts + 30 surviving controls), prompt stage2_v5 (= v4 + untrusted-field delimiters)

The prompt was never tuned on these cases (38 of 44 are new; 6 overlap r06en). Exa: 46 calls, $0.035. Sources: 28 ok, 7 unavailable, 6 uncited (changed sentence has no ref), 3 cleared at Stage 0.

## Reverts (14) — Sonnet flagged 9, Haiku 10
Caught (both models): "pets, though not very good ones" · "And it's good you should enroll in it" · "a fake claim, fakely … But get this" · "highly addictive" · "weird" · "illegal → undocumented" · "notoriety" replacing "a high profile" · a fan-twist rant · tabloid "alleged affair … soy" insertion (Sonnet G3).
Not flagged (both): a star spectral-class markup change (vandalism, not POV), the "Nicknamed the If Man" vandalism, "completed a master's degree" → "graduated", and an unsourced "influential families" sentence. Haiku alone flagged a body-description rewrite.
→ **Every revert that contains visible POV wording was caught by Sonnet.** The unflagged ones are vandalism or neutral changes, which are LiftWing's job rather than an NPOV detector's.

## Controls (30)
| | Any flag | Admin queue (conf ≥ 0.70) |
|---|---|---|
| Haiku | 3 (10%) | 2 (6.7%) |
| Sonnet | 2 (6.7%) | **1 (3.3%)** |

Reading the flagged controls:
- `en_control_1384186969` adds "to help pay for his college education" (both models G3, admin). The cited article only calls modelling "a successful side hustle". **The motive genuinely isn't in the cited source.**
- `en_control_1384184710` adds "a former Democrat now affiliated with the Socialist Party USA" (Haiku G1, admin). The cited interview has him describing himself as a Democrat. **The edit contradicts its cited source** (probably a good-faith update with newer information).
- `en_control_1384185611` (both G3, review queue): a causal "the fact that …" clause.

So the admin-queue "false alarms" are real WP:V gaps in good-faith edits that survived. "Surviving edit" is not the same as "clean edit". Measured strictly by label, Sonnet meets the ≤5% bar on the admin queue and Haiku doesn't.

## Recommendation
Use **Sonnet-class (or Gemini Hydrogen) for the admin queue**, and Haiku-class as a cheap first pass or the review queue. Re-measure the false-alarm rate on ≥100 controls before trusting a 5% bar: with 30 controls, one case is 3.3 points.

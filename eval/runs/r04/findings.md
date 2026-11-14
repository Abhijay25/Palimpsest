# r04 findings — first REAL edits (Finnish: 12 POV reverts + 20 surviving controls), prompt stage2_v2, live Exa sources

Exa: 37 calls, $0.02. Source status: 14 ok, 18 unavailable (dead or short pages on old Finnish refs; 56% unavailable).

## Results
| | Haiku | Sonnet |
|---|---|---|
| Controls flagged (false alarms) | 0/20 | **2/20 (10%)**, over the 5% bar |
| Controls → EXPAND_CONTEXT (escalation) | 7/20 | 5/20 |
| Reverts flagged | 5/12 | 7/12 |
| Reverts flagged where the source was ok | 4/5 | 4/5 |

- With an unavailable source, all 11 controls were correctly passed (the "judge framing only" path works).
- **Every one of the 7 abstentions and both false alarms came from controls whose source loaded.** That is where the problems are.

## Causes (read from cases)
1. **The silent source is treated as a contradiction.** `fi_control_21754136`: "buried in Lokalahti cemetery" → "buried in the *old* Lokalahti cemetery"; the source says only "Lokalahti cemetery". Sonnet flagged G1. `fi_control_19830601`: "will stand as a candidate in 2021" → "was elected in 2021", cited to a Yle candidate page. Sonnet flagged G1, Haiku abstained. Good-faith editors add details the cited passage doesn't cover all the time. This answers the parked "silent source" question with data: flagging silence produces false alarms on real edits.
2. **Stub and off-topic windows.** The Yle results page came back as a ~100-char header stub, and the Raptori article window is 3 sentences that don't mention the specific claims. The judges reasoned from near-nothing, which caused most of the EXPAND_CONTEXT verdicts.
3. The revert flags on loaded sources are all of the same kind: "added date or detail not in source" (e.g. `fi_revert_22391497` added an end date to an ambassador posting). Under the silent-source rule these would pass. The edit summary says POV, but the flagged content is not obviously POV, so **for real reverts, "reverted for POV" ≠ "the diff contains a G1/G2/G3 violation".** Unlabelled real reverts are weak ground truth; the English reverts, which you can read, are needed to judge.

## Changes for r05
- Stage 1: a window under 150 chars or sharing fewer than 2 claim tokens → treated as unavailable (commit "Treat stub and off-topic source windows as unavailable").
- Prompt stage2_v3: G1 requires contradiction, or the replacement of a source-supported value. A silent source on a neutral fact gives CLEAN_PASS (proposition marked UNSUPPORTED_EXTRAPOLATION, confidence ≤0.6), or EXPAND_CONTEXT only if the window points to the missing fact. **Unsupported motives are still G3** (asymmetry on purpose: WP:SYNTH is the main POV vector). This also settles spec Case 5 the conservative way.
- r05 re-runs these cases (Exa cache, so $0) plus the new English real-edit set, and re-runs the synthetic regression set to check that v3 doesn't lose recall.

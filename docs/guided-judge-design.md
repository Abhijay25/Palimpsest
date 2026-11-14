# Guided judge (stage2_v9): a fixed checklist, verdict decided in code

## Why

The admin makes the final decision; this tool keeps the human in the loop and makes that
decision easier. Its job is (1) not to miss an edit that deserves a look and (2) to state the
most plausible reason it needs review, with evidence. It never decides approval or rejection.

Hackathon scope: be very good at a small set of scenarios and expand later. Within those
scenarios the model answers narrow yes/no questions, each backed by exact quotes; code checks
the quotes and writes the reason. Suspicions outside the supported scenarios are not dropped:
they go to a lower-priority `review` tier with the judge's own reason, so nothing the model
noticed is silently lost.

Two tiers:
- `admin`: a supported scenario with validated evidence. Reason text is specific
  ("the edit changes 900 to 1,200; the cited source gives 900").
- `review`: the free-form judge flagged something the checklist did not validate, or a
  checklist answer whose quote failed validation. Reason text is phrased as a question for
  the reviewer ("possible loaded wording: 'notorious'; the source does not use it").

## Supported scenarios (v1)

| id | question to the model (per edit) | evidence required | verdict |
|---|---|---|---|
| S1 VALUE_SWAP | Did the edit replace a number, date, name, place or quantity from OLD_TEXT with a different value? Does the source state the old value, the new value, or neither? | old value + new value quoted from OLD/NEW; source quote if it states either | G1 if the source supports the old value or contradicts the new one |
| S2 CONTENTIOUS_CLAIM | Did the edit add a damaging claim (crime, arrest, misconduct, lawsuit, health, sexuality, extremism, insolvency) about an identifiable person or organisation? Does the source state it? | claim quoted from NEW; source quote if stated | G1 if the source does not state it |
| S3 ADDED_MOTIVE | Did the edit add a purpose, intent or cause? Does the source state that motive (attributed to someone)? | motive quoted from NEW; source quote if stated | G3 if not stated |
| S4 LOADED_WORDING | Did the edit add an evaluative adjective/adverb, intensifier, superlative or contested label that the source does not use? | the added word(s) quoted from NEW | G2 |
| S5 CERTAINTY_SHIFT | Did the edit remove a hedge or attribution, or swap a neutral reporting verb for a factive or doubt-casting one, relative to OLD and the source? | before/after phrases quoted | G2 |
| S6 REMOVED_CONTEXT | Did the edit delete sourced criticism, a qualifier, an attribution or one side of a dispute? | deleted text quoted from OLD; source quote | G2 |

Deterministic checks stay outside the model: hidden text (stealth scanner), future and
mismatched citation dates, cited-page render scan.

## Rules in code

1. Every quote attributed to OLD_TEXT, NEW_TEXT or the source must be an exact substring of it
   (whitespace-normalised). A "yes" whose quote fails validation is downgraded to the
   `review` tier with its stated reason, never silently discarded.
2. A finding counts only if the edit introduced it: S1/S4/S5 quotes from NEW_TEXT must not
   already appear in OLD_TEXT; S6 quotes must appear in OLD_TEXT and not in NEW_TEXT.
3. Verdict = most severe surviving finding (G1 > G3 > G2); none -> CLEAN_PASS. EXPAND_CONTEXT
   only when the model reports the source window is cut off (a separate yes/no) and there is
   no other surviving finding.
4. Confidence is computed, not self-reported: e.g. S1 with a source quote for the old value
   0.95, S1 with neither supported 0.65; S2/S3 0.85; S4/S5/S6 0.8. Routing thresholds then
   mean something.
5. The model writes a neutral rewrite only when at least one finding survives.
6. Output is mapped to the existing AuditOutput contract (spans from the validated quotes), so
   the API and teammates' UI do not change.

## Evaluation

Baseline stage2_v7 vs v8 (checklist inside the free-form prompt) vs v9 (guided) on Hydrogen
low, same 125 edits, reverts labelled by cause. Report per scenario: caught / should-catch, and
false alarms on the 60 clean edits. The winner is confirmed once on a fresh held-out set.

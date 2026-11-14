# r05fi — real Finnish edits re-judged with stage2_v3 + the stub/off-topic window rule (same 32 cases as r04)

Exa: 22 calls (retries of earlier failures), $0.006. Sources: 12 ok, 20 unavailable (2 more ok sources reclassified as stubs or off-topic).

| | r04 (v2) Haiku / Sonnet | r05fi (v3) Haiku / Sonnet |
|---|---|---|
| Controls flagged (false alarms, of 20) | 0 / 2 | **0 / 0** |
| Controls → EXPAND_CONTEXT | 6 / 4 | 2 / 0 |
| Reverts flagged (of 12) | 6 / 7 | 2 / 2 |

## Were the "lost" revert flags real violations? (I read every revert via its English gloss)
- **Still caught by both models (clear POV):** `fi_revert_16118899` appends an unsourced editorial conclusion ("So gaining Swedish power was largely thanks to Finland"; reverted as "unsourced comment"). `fi_revert_13441433` recasts sourced facts as "conjecture" (reverted as "unsourced nonsense").
- **Correctly passed:** place-name spelling changes, an added home district, a long biography addition, and an added end date for an ambassador posting. These were reverted for non-POV reasons, and v2's G1 flags on them came from the silent-source problem.
- **`fi_revert_15356383` (Mainila shots)** flips "Russians have *not* admitted it was staged" to "Russians *have later admitted*…". The reverter called the YLE source speculation. **The cited YLE article literally says "Later the Russians too have admitted that the Soviet Union staged it."** So the edit is entailed by its own citation. Passing it is the design working (grounded in the cited source, no parametric knowledge). Whether the source is right is a WP:RSP / source-reliability question, not an entailment question.
- **Debatable [review]:** `fi_revert_19464447` removes "as a fascist organisation" from the Civil Guard's dissolution sentence. Both models passed it (the source was unavailable). Removing a characterisation the old text attributed to the Allied Control Commission could count as stripping a qualifier (G2). I'd lean towards flagging deletions of qualifiers, but with an unavailable source the judge can't tell whether the qualifier was sourced.

## Takeaways
1. **The silent-source rule removed every false alarm and most abstentions without losing the clear POV insertions.**
2. "Reverted with a POV-ish summary" is weak ground truth: of 12 Finnish reverts, only 2–3 contain a violation visible in the diff.
3. Next gap: **deletions**. The rubric focuses on what NEW asserts; removing a sourced qualifier or attribution is under-specified.

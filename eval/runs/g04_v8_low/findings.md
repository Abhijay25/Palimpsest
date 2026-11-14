# g04: stage2_v8 (checklist inside the free-form prompt) vs stage2_v7, Hydrogen LOW

Same 125 cases as g03 (124 judged): en_reverts3 + en_controls3, fi_blind_reverts + fi_blind_controls, blp_silence. Reverts labelled by cause in eval/labels/g03_reverts_sonnet.json. Tiers: admin >= 0.70, review 0.45-0.70. 124 Hydrogen calls: 462k input, 31k output, 64k thinking tokens.

| group | v7 (g03_hydrogen_low) | v8 (this run) |
|---|---|---|
| clean controls flagged (admin), en / fi | 1/30, 1/30 | 1/30, 1/30 |
| BLP synthetic correct | 24/24 | 24/24 |
| reverts: FACTUAL_ERROR (should flag) | 1/5 | 1/5 |
| reverts: POV_FRAMING | 5/6 | 5/6 |
| reverts: UNSOURCED_CONTENTIOUS | 4/6 | 4/6 |
| reverts: REMOVED_SOURCED_CONTENT | 1/2 | 1/2 |
| reverts: VANDALISM | 6/8 | 7/8 |
| reverts that need no flag (NON_CONTENT, UNCLEAR), flagged | 0/14 | 0/14 |

Only one decision changed (fi_revert_23153846, vandalism, now caught). The checklist inside the free-form prompt does not move recall: the gap is factual errors (1/5).

Why factual errors are missed: in 3 of 4 misses the model marked the changed claim UNSUPPORTED_EXTRAPOLATION in its own propositions, then returned CLEAN_PASS at 0.50-0.55 (birth year 1997 -> 2009 uncited; production company swapped; "oldest MP" claim added). The judgement exists; the harness discards it.

Offline what-if (zero calls, from these outputs): a deterministic value-swap detector + the judge's own UNSUPPORTED/CONTRADICTED mark -> review tier. After making the detector language-neutral (punctuation, possessives, sentence-initial capitals, inflection/extension by shared prefix, spelling fixes, same-type pairs), factual errors 1/5 -> 3/5 (2 in review tier), clean controls given a review flag 2/60 (one is a real name replacement whose source was unavailable). Tuned on this set: must be confirmed on the isolated scout's real value swaps and controls before it counts.

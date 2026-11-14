# Replay 1 findings

## What was tested
113 randomly sampled real edits from random English, Swedish, and Finnish articles, audited with the isolated scout. Ground truth comes from later history: reverted, corrected by another editor, or stood for 30+ days. Each edit was audited through the live API (default stage2_v10, Exa highlights, value check, out-of-sync, citation rot, and stealth), with 4 concurrent requests; Gemini temperature 0, seed 7. Sampling limitations are described in [the scout README](../../scout/history_random/README.md).

## Results by language and outcome

| lang | ground truth | n | admin | review | none | flag points at the later change | errors |
|---|---|---|---|---|---|---|---|
| en | corrected | 12 | 3 | 2 | 7 | 1 | 0 |
| en | reverted | 12 | 5 | 0 | 7 | 5 | 0 |
| en | stood | 16 | 0 | 1 | 15 | 0 | 0 |
| fi | corrected | 12 | 4 | 0 | 8 | 3 | 0 |
| fi | reverted | 12 | 7 | 1 | 4 | 6 | 0 |
| fi | stood | 16 | 1 | 1 | 14 | 0 | 0 |
| sv | corrected | 12 | 2 | 3 | 7 | 1 | 0 |
| sv | reverted | 5 | 1 | 0 | 4 | 1 | 0 |
| sv | stood | 16 | 0 | 2 | 14 | 0 | 0 |

Among stood edits, 1/48 received an admin flag: Suomenlinna (MOTIVE; one admin and one review MOTIVE flag). The four review-only stood edits were Samantha Strauss (CITED_PAGE), Udo Kier (HIDDEN_TEXT), Anna Kettner (CITED_PAGE), and Fredrik Stenfelt (CITED_PAGE). Among reverted edits, 14/29 were flagged; 12 of those flags point at the reverted text. Among corrected edits, 14/36 were flagged.

## Miss diagnosis

A single gemini-4-argon call per miss (temperature 0) judged 11 of 37 misses catchable from the edit itself. This is model judgment, not human verification.

| Category | Misses | Catchable |
|---|---:|---:|
| DISPUTE_OR_PREFERENCE | 3 | 1 |
| FACTUAL_SWAP | 1 | 1 |
| OTHER | 2 | 0 |
| REFINEMENT | 10 | 0 |
| REMOVED_CONTENT | 2 | 2 |
| STYLE_FORMAT | 13 | 1 |
| UNSOURCED_CLAIM | 5 | 5 |
| VANDALISM_OR_TEST | 1 | 1 |
| **Total** | **37** | **11** |

### Catchable misses

| Page | Label | Category | What was wrong |
|---|---|---|---|
| Zoran Terzić | reverted | VANDALISM_OR_TEST | Inserted a spam link inside the date parameter of a maintenance template. |
| Albert J. Goddard | reverted | STYLE_FORMAT | Broke image file markup by inserting a wikilink in the filename; also listed “Republican” as an occupation. |
| Red Line (Chennai Metro) | reverted | FACTUAL_SWAP | Changed the sourced line length without changing its citation and introduced broken template syntax in the footnote. |
| Sakari Tamminen | corrected | UNSOURCED_CLAIM | Changed residence from Portugal to Italy without a new source, while leaving the Portugal citation; also broke a wikilink. |
| Udo Kier | corrected | REMOVED_CONTENT | Accidentally deleted the death year (2025) while adding the place of death. |
| Ali Leiniö | reverted | UNSOURCED_CLAIM | Added a specific birth year (1977) that the cited article could not establish. |
| Dugongi | reverted | UNSOURCED_CLAIM | Added an unsourced, factually incorrect claim that herbivorous dugongs also eat fish. |
| Ali Leiniö | reverted | UNSOURCED_CLAIM | Added an uncited claim of death and a specific death date. |
| Dugongi | reverted | UNSOURCED_CLAIM | Added factual claims about threats, diseases, and reproductive vulnerability without sourcing them. |
| Moa Svan | reverted | REMOVED_CONTENT | Unexplainedly removed multiple paragraphs of sourced biographical information. |
| Påskupploppen i Sverige 2022 | reverted | DISPUTE_OR_PREFERENCE | Changed the event name in the infobox and lead against the page title and talk-page consensus. |

## Recall and latency

For reverted plus corrected edits, recall on catchable problems is 28/(28+11) = **71.8%**: 28 flagged edits (14 reverted + 14 corrected) divided by those flags plus 11 catchable misses. This assumes flagged edits are catchable; the miss diagnoses are model-judged, not human-verified. Latency was **4.8 s p50**, **37.2 s max**.

## Next actions

Unsourced claims are the largest catchable gap (5/11). By design, the judge requires sources only for damaging BLP claims. Review-tier noise on stood edits comes from cited-page and hidden-text checks; examine these in the security phase.

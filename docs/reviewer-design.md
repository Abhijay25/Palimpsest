# Second-opinion reviewer (Argon over Hydrogen)

## Why

Hydrogen judges each changed paragraph on its own. A stronger model that sees the whole
edit's results once can (1) confirm or adjust each flag with the evidence in hand, (2) write
the admin-facing reason in plain language (no schema words such as "OLD_TEXT" or "boolean
polarity"), and (3) look again at borderline clean results, which is where factual errors
are missed today (g04: the judge marked the changed claim unsupported, then passed it).

Earlier measurement (g02, 14 cases): Argon as the primary judge was slower than Hydrogen
(p50 9.0 s vs 4.4 s) and no more accurate, so it is not used as the judge. As a reviewer it
runs once per edit and only when there is something to review.

## When it runs

- Every edit with at least one flag (any tier, any check), and
- borderline clean edits: a unit judged CLEAN_PASS whose propositions include
  UNSUPPORTED_EXTRAPOLATION or CONTRADICTED for changed text, or a detected value swap.
- Nothing else: Stage-0-clean edits and confident clean passes never call it.

## What it sees

One request per edit: page title, language, each unit's old/new text (changed sentences plus
one sentence of context), the source excerpts the judge saw (highlights), and the candidate
findings: Hydrogen flags, deterministic findings (value swaps, citation dates, hidden text),
and the borderline propositions. Untrusted fields keep the existing delimiters.

## What it may do (enforced in code)

Per candidate, one decision: `confirm`, `to_review` (admin -> review, with a reason), or
`raise_to_review` (borderline clean -> review). It writes `title` (<= 80 chars) and `reason`
(<= 2 sentences, plain language, quoting the edit and the source). It may NOT delete a
candidate: the worst outcome for a Hydrogen flag is the review tier, so the admin still sees
it. It never raises anything to admin on its own; admin needs Hydrogen's verdict or a
deterministic check. Its output quotes are validated as exact substrings like the guided
judge; a failed quote keeps the original reason.

## Cost and latency

One Argon call per reviewed edit, LOW thinking, run after the judges finish. Expected only on
the ~15-30% of edits that have flags or borderline passes. Its latency adds to those edits
only; the UI already shows a loading state. If it fails or times out (budget 12 s), the
Hydrogen result stands unchanged and the response says the review was skipped.

## Evaluation

Same 125 cases (g03/g04 set): Hydrogen alone vs Hydrogen + reviewer. Report per revert cause
(caught in admin / review), clean controls flagged per tier, reviewer calls, added p50/p95
latency, tokens. Then confirm once on the isolated scout's real cases. Success: recall up
(factual errors especially) with clean-control admin flags not above 2/60 and review flags
not above 5%.

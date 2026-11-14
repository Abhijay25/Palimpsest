# s01 — stealth scanner, Pillar 1 + Pillar 2 triage (Haiku and Sonnet as gemini-decision-1 stand-ins)

Cases: 7 spec attacks, 20 evasion attacks, 36 real Finnish and 6 real English hidden-channel additions (benign controls).

| | Haiku | Sonnet |
|---|---|---|
| Accuracy (exact status) | 87.0% | 87.0% |
| False alarms (benign → flagged) | 1/39 (2.6%) | 1/39 |
| Misses (attack → not flagged) | 5/30 (16.7%) | 5/30 |
| Pillar 1 alone, accuracy | 82.6% | — |
| Pillar 1 latency p50 / p95 | 0.28 / 0.76 ms | — |

- **Every miss comes from Pillar 1**: the hidden text never reached triage. Evasions missed: white-on-white with the longhand `background-color`, a near-zero `font-size:0.01em`, the HTML5 `hidden` attribute, an instruction in a non-rendering template parameter, and an instruction split by zero-width characters.
- The one false alarm: a Cyrillic interlanguage link (`[[ru:…]]`) with one typed Latin letter, flagged as a homoglyph.
- 3 more mismatches are CLEAN vs BENIGN_NOTES_ONLY. Both mean "no flag" to an admin, and the labels themselves were uncertain.
- Triage behaved: no injected text made the judges deviate. All 43 triage items in each batch came back as valid verdicts.
- Real data: **zero real prompt injections** in 42 real hidden-channel additions. One real homoglyph vandalism ("pеnis" with Cyrillic е) was caught.

Fixes for s02: deterministic Pillar 1 rules for each miss plus an interwiki exemption. Because those fixes target the s01 cases directly, s02 adds a **held-out** set (`attacks_heldout.jsonl`) written by an agent that never saw the scanner code. That held-out number is the honest one.

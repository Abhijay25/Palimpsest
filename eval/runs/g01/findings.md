# g01: first Gemini trial (gemini-4-hydrogen, stage2_v7, SDK-default thinking)

11 cases: spec benchmark 1-5, 3 Finnish reverts (2 Sonnet caught, 1 Sonnet missed), 3 Finnish controls (2 Haiku false alarms, 1 plain). 10 Gemini calls, 3 Exa calls ($0.001).

| case | Hydrogen | Sonnet (r11fi/r15spec) |
|---|---|---|
| spec 1-4 | CLEAN, G1 1.00, G2 0.98, G3 0.98 (all correct) | correct |
| spec 5 (EXPAND guardrail) | G1 0.95 | EXPAND 0.80 |
| fi_revert_22878377 | G1 0.98: unsourced "KGB agent 1950-1975" claim about a named person (v7 BLP rule) | G2 0.80 |
| fi_revert_16572122 | G1 0.98 | G1 0.85 |
| fi_revert_22022025 | CLEAN 0.55 (missed, as Sonnet) | CLEAN 0.80 |
| fi_control_20798678 | CLEAN 0.60 (Haiku false alarm avoided) | CLEAN |
| fi_control_15334154 | G1 0.90: unsourced claim that a named man was violent | CLEAN 0.50 |
| fi_control_18715399 | CLEAN 0.50 | CLEAN |

Findings:
1. **Latency is the blocker:** stage 2 per call 4.7-26 s (median ~12.7 s) at default thinking. Claude stand-ins were ~1.5 s. Caveat found afterwards: these timings started before the concurrency semaphore (4 slots, 10 calls), so later calls include queueing; the first wave (4.7-9.9 s) is the closest to true per-call time. Fixed in d5734f2 (timer inside the semaphore, token usage printed). Next: measure GEMINI_THINKING_LEVEL=LOW/MINIMAL on the same few cases.
2. **Confidence is saturated:** every flag is 0.90-1.00, so the 0.70 admin / 0.45 review thresholds separate nothing. Thresholds must be re-fit on Hydrogen (or routing must use verdict + span evidence rather than self-reported confidence).
3. **BLP rule fires harder on Hydrogen:** both real-person claims (KGB agent; violent boyfriend) go to G1 at >=0.90. The control case is the same unsourced violence claim earlier judged a real BLP problem patrol missed, so it is a defensible flag, not a clear false alarm.
4. **Spec case 5:** the window says the spokesperson declined to give the new figure; Hydrogen reads the added "4,200" as contradicting it (G1) rather than as a pointer to missing context. Our case wording differs from the spec's; one case, no prompt change made for it.
5. `gemini-decision-1` (default triage model) is not available to this key; candidates listed: gemini-3.5-flash-lite, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon.
6. Token usage is not recorded per call, so cost cannot be computed yet.

# r05s — regression check: prompt stage2_v3 on the 45 fixed-source cases (same set as r02/r03)

| | v2 (r03) Haiku / Sonnet | v3 (r05s) Haiku / Sonnet |
|---|---|---|
| Recall (planted violations flagged) | 100% / 100% | 100% / 100% |
| Clean controls flagged | 0% / 0% | 0% / 0% |
| Exact label | 42/45 / 42/45 | **44/45 / 43/45** |
| `en_spec_05` (silent source, should abstain) | G1 / G1 (wrong) | EXPAND / EXPAND (correct) |

v3's silent-source rule cost no recall: unsupported motives are still caught as G3, and contradictions are still caught as G1. The remaining misses are the Finnish hedge-removal boundary cases (`fi_synth2_03`, `fi_synth2_04`), which are flagged either way.

Cost: one batch of 45 per model worked fine (no parse errors). Haiku ~100k and Sonnet ~68k subagent tokens, against ~250k for 4 batches in r03.

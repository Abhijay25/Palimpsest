# B2 check

Live measurement did not start: the in-process `audit-diff` path stalls at
Starlette/AnyIO's `run_in_threadpool` before Stage 0, Exa, or Gemini. A
15-second diagnostic attempt on `en_control_1384233971` exited 124 with no
output. This is also reproducible by the existing `tests/test_api.py` clean
case, so it is not a B2 source or model failure.

| set | completed | admin | review | flagged |
| --- | ---: | ---: | ---: | ---: |
| 60 clean controls | 0 / 60 | n/a | n/a | n/a |
| 5 source corrections | 0 / 5 | n/a | n/a | n/a |

Three contract-example reasons exercised by the mocked B2 tests:

1. The edit says “The allegation was proven.”; the cited source says “The final audit found the allegation unsupported.”
2. The edit says “The treatment works for everyone.”; the cited source says “The study did not establish benefit for all patients.”
3. The edit says “The allegation was proven.”; the cited source says “The final audit found the allegation unsupported.”

Ready command after the thread-pool issue is resolved (Gemini and Exa are read
from `.env`):

```sh
PALIMPSEST_USE_GEMINI=1 UV_CACHE_DIR=/tmp/palimpsest-uv uv run python -m palimpsest diagnose --case eval/cases/en_controls3.jsonl --case-id en_control_1384233971 --json
```

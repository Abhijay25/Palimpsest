# OUT_OF_SYNC scout verification

The sandbox's network policy blocks the public fi.wikipedia API, so no live counts
were produced here. Run this from a network-enabled environment:

```sh
UV_CACHE_DIR=/tmp/palimpsest-uv-cache uv run python eval/scout/history/out_of_sync.py
```

The script reads both 25-row history sets, fetches each parent/bad revision pair
at no more than one request per second, and replaces this file with deterministic
and semantic OUT_OF_SYNC counts for swaps and controls. Semantic counts require
`GEMINI_API_KEY` and `PALIMPSEST_USE_GEMINI=1`; otherwise they are reported as zero.

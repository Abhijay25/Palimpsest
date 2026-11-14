from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import build_membership
from .history import deterministic_sample
from .io import atomic_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    full = build_membership(args.assets, args.lock)
    sample = deterministic_sample(full, per_language=2)
    atomic_json(args.output / "full-corpus.json", full)
    atomic_json(args.output / "sample-corpus.json", sample)
    print(json.dumps({"scope": "full", "counts": full["expected_counts"], "sample_counts": sample["expected_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

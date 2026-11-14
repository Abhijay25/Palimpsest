"""Measure flag-set stability across repeated fresh audit-diff requests.

Usage: python -I eval/determinism.py <edits.jsonl>... --out <dir> --repeats 3
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# -I removes the repository root from sys.path.  Keep the evaluator self-contained
# while importing (rather than copying) history_replay's request construction.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.history_replay import audit

type FlagKey = tuple[str, str, str]


def _flags(result: dict[str, object]) -> frozenset[FlagKey]:
    raw = result.get("flags")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        (
            str(flag.get("kind", "")),
            str(flag.get("tier", "")),
            str(flag.get("anchor_text", "")),
        )
        for flag in raw
        if isinstance(flag, dict)
    )


def _load_edits(paths: list[str]) -> list[dict[str, object]]:
    edits: list[dict[str, object]] = []
    for filename in paths:
        for line in Path(filename).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{filename} contains a non-object JSON line")
            edits.append({str(key): item for key, item in value.items()})
    return edits


def _markdown_flags(flags: frozenset[FlagKey]) -> list[str]:
    return [
        f"  - `{kind}` / `{tier}` / {anchor!r}" for kind, tier, anchor in sorted(flags)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for edit in _load_edits(args.files):
        runs: list[frozenset[FlagKey]] = []
        errors: list[str | None] = []
        for _ in range(args.repeats):
            started = time.monotonic()
            try:
                result = audit(edit, fresh=True)
                errors.append(None)
                runs.append(_flags(result))
            except Exception as exc:  # noqa: BLE001 - record an unavailable run
                errors.append(f"{type(exc).__name__}: {exc}")
                runs.append(frozenset())
            print(
                f"{edit.get('lang', '')} {edit.get('page_title', '')} "
                f"run {len(runs)}/{args.repeats}: {time.monotonic() - started:.1f}s",
                flush=True,
            )
        stable = not any(errors) and len(set(runs)) == 1
        bucket = str(edit.get("bucket") or edit.get("label") or "unknown")
        rows.append(
            {
                "lang": edit.get("lang"),
                "page_title": edit.get("page_title"),
                "rev_id": edit.get("rev_id"),
                "bucket": bucket,
                "stable": stable,
                "errors": errors,
                "runs": [sorted(run) for run in runs],
            }
        )
    (out / "rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts = buckets[str(row["bucket"])]
        counts["stable" if row["stable"] else "unstable"] += 1
    table = [
        "| bucket | stable | unstable |",
        "|---|---:|---:|",
        *[
            f"| {bucket} | {counts['stable']} | {counts['unstable']} |"
            for bucket, counts in sorted(buckets.items())
        ],
    ]
    (out / "table.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    unstable = ["# Unstable flag sets", ""]
    for row in rows:
        if row["stable"]:
            continue
        unstable.append(
            f"## {row['lang']} — {row['page_title']} (revision {row['rev_id']})"
        )
        reported_runs = row["runs"]
        if not isinstance(reported_runs, list):
            continue
        for index, run in enumerate(reported_runs, start=1):
            if not isinstance(run, list):
                continue
            unstable.append(f"Run {index}:")
            flags: frozenset[FlagKey] = frozenset(
                (str(item[0]), str(item[1]), str(item[2]))
                for item in run
                if isinstance(item, (list, tuple)) and len(item) == 3
            )
            unstable.extend(_markdown_flags(flags))
        raw_errors = row["errors"]
        errors = (
            [str(error) for error in raw_errors if error]
            if isinstance(raw_errors, list)
            else []
        )
        if errors:
            unstable.extend(f"  - error: {error}" for error in errors)
        unstable.append("")
    (out / "unstable.md").write_text("\n".join(unstable) + "\n", encoding="utf-8")
    print("\n".join(table))


if __name__ == "__main__":
    main()

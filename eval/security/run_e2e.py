"""POST security cases to a running audit API and write a human-readable scorecard.

This runner intentionally uses only the standard library so it can run with
``python -I``.  API failures are recorded per row and never make the process fail.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

DEFAULT_API: Final[str] = "http://127.0.0.1:8765/api/v1/audit-diff"
_TIER_RANK: Final[dict[str, int]] = {"none": 0, "review": 1, "admin": 2}


@dataclass(frozen=True)
class Expected:
    must_flag_kinds: tuple[str, ...]
    accept_kinds: tuple[str, ...]
    min_tier: str
    must_not_flag_kinds: tuple[str, ...]


@dataclass(frozen=True)
class SecurityCase:
    case_id: str
    lang: str
    bucket: str
    page_title: str
    old_wikitext: str
    new_wikitext: str
    old_text: str
    new_text: str
    ref_urls: tuple[str, ...]
    expected: Expected
    notes: str


@dataclass(frozen=True)
class FlagSummary:
    kind: str
    tier: str
    reason: str


@dataclass(frozen=True)
class ScoredRow:
    case_id: str
    lang: str
    bucket: str
    expected: dict[str, object]
    got_kinds: list[str]
    flags: list[dict[str, str]]
    hit: bool
    miss: bool
    false_positive: bool
    error: str | None
    seconds: float


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(value)


def case_from_data(value: object) -> SecurityCase:
    """Validate the small JSONL contract without importing application code."""
    if not isinstance(value, dict):
        raise TypeError("case must be an object")
    expected_value = value.get("expected")
    if not isinstance(expected_value, dict):
        raise TypeError("expected must be an object")
    required_strings = (
        "case_id",
        "lang",
        "bucket",
        "page_title",
        "old_wikitext",
        "new_wikitext",
        "old_text",
        "new_text",
        "notes",
    )
    strings: dict[str, str] = {}
    for key in required_strings:
        item = value.get(key)
        if not isinstance(item, str):
            raise TypeError(f"{key} must be a string")
        strings[key] = item
    tier = expected_value.get("min_tier")
    if not isinstance(tier, str) or tier not in _TIER_RANK:
        raise ValueError("expected.min_tier must be admin, review, or none")
    return SecurityCase(
        case_id=strings["case_id"],
        lang=strings["lang"],
        bucket=strings["bucket"],
        page_title=strings["page_title"],
        old_wikitext=strings["old_wikitext"],
        new_wikitext=strings["new_wikitext"],
        old_text=strings["old_text"],
        new_text=strings["new_text"],
        ref_urls=_strings(value.get("ref_urls"), "ref_urls"),
        expected=Expected(
            must_flag_kinds=_strings(
                expected_value.get("must_flag_kinds"), "expected.must_flag_kinds"
            ),
            accept_kinds=_strings(
                expected_value.get("accept_kinds", []), "expected.accept_kinds"
            ),
            min_tier=tier,
            must_not_flag_kinds=_strings(
                expected_value.get("must_not_flag_kinds"),
                "expected.must_not_flag_kinds",
            ),
        ),
        notes=strings["notes"],
    )


def load_cases(paths: list[Path]) -> list[SecurityCase]:
    cases: list[SecurityCase] = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                cases.append(case_from_data(json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return cases


def _request_body(case: SecurityCase) -> dict[str, object]:
    return {
        "lang_code": case.lang,
        "page_title": case.page_title,
        "old_revision_id": 1,
        "new_revision_id": 2,
        "editor_username": "security-eval",
        "old_text": case.old_text,
        "new_text": case.new_text,
        "old_wikitext": case.old_wikitext,
        "new_wikitext": case.new_wikitext,
        "ref_urls": list(case.ref_urls),
    }


def audit(case: SecurityCase, api_url: str) -> list[FlagSummary]:
    request = urllib.request.Request(
        api_url,
        json.dumps(_request_body(case), ensure_ascii=False).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=310) as response:
        payload: object = json.load(response)
    if not isinstance(payload, dict):
        raise TypeError("API response is not an object")
    raw_flags = payload.get("flags")
    if not isinstance(raw_flags, list):
        raise TypeError("API response flags is not a list")
    summaries: list[FlagSummary] = []
    for flag in raw_flags:
        if not isinstance(flag, dict):
            continue
        kind, tier, reason = flag.get("kind"), flag.get("tier"), flag.get("reason")
        if isinstance(kind, str) and isinstance(tier, str) and isinstance(reason, str):
            summaries.append(FlagSummary(kind, tier, reason))
    return summaries


def score_case(
    case: SecurityCase,
    flags: list[FlagSummary],
    seconds: float,
    error: str | None = None,
) -> ScoredRow:
    """Score one API result against all required and prohibited kinds."""
    present_kinds = {flag.kind for flag in flags}
    expected_rank = _TIER_RANK[case.expected.min_tier]
    required_kinds = (
        case.expected.accept_kinds
        if case.expected.accept_kinds
        else case.expected.must_flag_kinds
    )
    has_required = (
        any(
            flag.kind == kind and _TIER_RANK.get(flag.tier, 0) >= expected_rank
            for kind in required_kinds
            for flag in flags
        )
        if case.expected.accept_kinds
        else all(
            any(
                flag.kind == kind and _TIER_RANK.get(flag.tier, 0) >= expected_rank
                for flag in flags
            )
            for kind in required_kinds
        )
    )
    has_prohibited = bool(present_kinds & set(case.expected.must_not_flag_kinds))
    is_control = case.bucket == "controls"
    false_positive = has_prohibited or (is_control and bool(flags))
    hit = error is None and has_required
    return ScoredRow(
        case_id=case.case_id,
        lang=case.lang,
        bucket=case.bucket,
        expected={
            "must_flag_kinds": list(case.expected.must_flag_kinds),
            "accept_kinds": list(case.expected.accept_kinds),
            "min_tier": case.expected.min_tier,
            "must_not_flag_kinds": list(case.expected.must_not_flag_kinds),
        },
        got_kinds=sorted(present_kinds),
        flags=[asdict(flag) for flag in flags],
        hit=hit,
        miss=error is None and not has_required,
        false_positive=false_positive,
        error=error,
        seconds=round(seconds, 3),
    )


def run_case(case: SecurityCase, api_url: str) -> ScoredRow:
    started = time.monotonic()
    try:
        flags = audit(case, api_url)
        error = None
    except Exception as exc:  # noqa: BLE001 - a probe failure belongs in its row
        flags = []
        error = f"{type(exc).__name__}: {exc}"
    return score_case(case, flags, time.monotonic() - started, error)


def bucket_summary(rows: list[ScoredRow]) -> dict[str, dict[str, float | int]]:
    """Return per-bucket counts and conventional median response time."""
    grouped: dict[str, list[ScoredRow]] = defaultdict(list)
    for row in rows:
        grouped[row.bucket].append(row)
    summary: dict[str, dict[str, float | int]] = {}
    for bucket, values in sorted(grouped.items()):
        summary[bucket] = {
            "n": len(values),
            "hit": sum(row.hit for row in values),
            "miss": sum(row.miss for row in values),
            "fp": sum(row.false_positive for row in values),
            "errors": sum(row.error is not None for row in values),
            "p50_seconds": round(statistics.median(row.seconds for row in values), 3),
        }
    return summary


def table_markdown(rows: list[ScoredRow]) -> str:
    lines = [
        "| bucket | n | hit | miss | fp | errors | p50 seconds |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for bucket, values in bucket_summary(rows).items():
        lines.append(
            "| {bucket} | {n} | {hit} | {miss} | {fp} | {errors} | {p50_seconds:.3f} |".format(
                bucket=bucket, **values
            )
        )
    return "\n".join(lines) + "\n"


def misses_markdown(rows: list[ScoredRow]) -> str:
    lines = ["# Misses", ""]
    misses = [row for row in rows if row.miss or row.false_positive or row.error]
    if not misses:
        return "\n".join([*lines, "No misses, false positives, or API errors.", ""])
    for row in misses:
        lines.extend(
            [
                f"## {row.case_id}",
                "",
                f"- Expected: `{json.dumps(row.expected, ensure_ascii=False)}`",
                f"- Got kinds: `{', '.join(row.got_kinds) or 'none'}`",
                f"- Error: `{row.error or 'none'}`",
                "- Flag reasons:",
            ]
        )
        if row.flags:
            lines.extend(
                f"  - `{flag['kind']}` / `{flag['tier']}`: {flag['reason']}"
                for flag in row.flags
            )
        else:
            lines.append("  - none")
        lines.append("")
    return "\n".join(lines)


def write_reports(rows: list[ScoredRow], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rows.json").write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "table.md").write_text(table_markdown(rows), encoding="utf-8")
    (output_dir / "misses.md").write_text(misses_markdown(rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()
    try:
        cases = load_cases(args.cases)
    except (OSError, TypeError, ValueError) as exc:
        print(f"Could not load cases: {type(exc).__name__}: {exc}")
        return
    # The API bounds its model work; four in-flight requests are its established
    # throughput setting and also keep this probe from serializing slow rot paths.
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda case: run_case(case, args.api), cases))
    write_reports(rows, args.out)
    print(table_markdown(rows), end="")


if __name__ == "__main__":
    main()

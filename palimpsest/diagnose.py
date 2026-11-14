"""Single-edit diagnostic CLI sharing the audit-diff pipeline."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from pydantic import ValidationError

from palimpsest.api import (
    AuditDiffRequest,
    AuditDiffResponse,
    JudgeUnavailableError,
    audit_diff_logic,
    get_auditor_provider,
    get_fetcher,
    get_judge_backend,
)
from palimpsest.schema import Case


class NoJudgeJson(TypedDict):
    error: str
    stages_ran: list[str]
    latency_ms: dict[str, float]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m palimpsest diagnose")
    parser.add_argument("--case", type=Path, help="JSONL case file")
    parser.add_argument("--case-id", help="case_id to select from --case")
    parser.add_argument("--old", help="old edit text")
    parser.add_argument("--new", help="new edit text")
    parser.add_argument("--lang", help="Wikipedia language code")
    parser.add_argument("--title", help="page title")
    parser.add_argument("--ref", action="append", default=[], help="reference URL")
    parser.add_argument("--json", action="store_true", help="print JSON")
    return parser


def _request_from_case(path: Path, case_id: str | None) -> AuditDiffRequest:
    cases = [
        Case.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if case_id is None:
        if len(cases) != 1:
            raise ValueError("--case-id is required when --case has multiple rows")
        case = cases[0]
    else:
        selected = [case for case in cases if case.case_id == case_id]
        if len(selected) != 1:
            raise ValueError(f"no unique case_id {case_id!r} in {path}")
        case = selected[0]
    return AuditDiffRequest(
        lang_code=case.lang,
        page_title=case.page_title,
        old_revision_id=0,
        new_revision_id=1,
        editor_username="diagnose",
        old_text=case.old_text,
        new_text=case.new_text,
        ref_urls=case.ref_urls,
        old_wikitext=case.old_wikitext,
        new_wikitext=case.new_wikitext,
    )


def _request_from_inline(args: argparse.Namespace) -> AuditDiffRequest:
    required = ("old", "new", "lang", "title")
    missing = [f"--{name}" for name in required if getattr(args, name) is None]
    if missing:
        raise ValueError(f"inline edit requires {', '.join(missing)}")
    return AuditDiffRequest(
        lang_code=args.lang,
        page_title=args.title,
        old_revision_id=0,
        new_revision_id=1,
        editor_username="diagnose",
        old_text=args.old,
        new_text=args.new,
        ref_urls=args.ref,
    )


def _table(rows: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}}  {value}" for label, value in rows)


def _response_rows(response: AuditDiffResponse) -> list[tuple[str, str]]:
    latency = response.latency_ms
    rows = [
        ("stage reached", str(response.pipeline_stage_reached)),
        (
            "latency ms",
            " ".join(
                f"{name}={getattr(latency, name):.1f}"
                for name in ("stage0", "stealth", "stage1", "stage2", "render", "total")
            ),
        ),
        (
            "stealth",
            f"{response.stealth.status} ({response.stealth.finding_count} findings)",
        ),
        ("render", response.render.status),
        ("verdict", response.verdict.value),
        ("confidence", f"{response.confidence:.3f}"),
        ("route", response.route),
        ("reason", str(response.reason or "none")),
        ("reason text", response.reason_text or "none"),
        ("citation dates", response.citation_dates.status),
        ("citation dates error", response.citation_dates.error or "none"),
        (
            "citation date findings",
            "; ".join(
                f"{finding.code} date={finding.rendered_date} "
                f"revision={finding.revision_timestamp.isoformat()} url={finding.url}"
                for finding in response.citation_dates.findings
            )
            or "none",
        ),
        (
            "units",
            "; ".join(f"{unit.index}:{unit.verdict.value}" for unit in response.units),
        ),
        (
            "atomic propositions",
            "; ".join(
                f"[{item.clause_type.value}/{item.source_entailment.value}] "
                f"{item.clause_text!r} quote={item.evidence_quote_from_ref!r}"
                for item in response.atomic_propositions
            )
            or "none",
        ),
        (
            "flagged spans",
            "; ".join(
                f"[{span.guideline_violated}] {span.exact_substring!r} "
                f"context={span.context_sentence!r}"
                for span in response.flagged_spans
            )
            or "none",
        ),
        ("neutral rewrite", response.neutral_rewrite or "none"),
        ("trust delta", f"{response.editor_trust_delta:.2f}"),
    ]
    return rows


async def _run(request: AuditDiffRequest) -> AuditDiffResponse:
    return await audit_diff_logic(
        request, get_fetcher(), get_judge_backend(), get_auditor_provider()
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        request = (
            _request_from_case(args.case, args.case_id)
            if args.case is not None
            else _request_from_inline(args)
        )
    except (OSError, ValidationError, ValueError) as exc:
        parser.error(str(exc))
    try:
        response = asyncio.run(_run(request))
    except JudgeUnavailableError as exc:
        if args.json:
            data: NoJudgeJson = {
                "error": "No judge is enabled; no verdict was produced.",
                "stages_ran": ["stealth", "stage0"],
                "latency_ms": {"stealth": exc.stealth_ms, "stage0": exc.stage0_ms},
            }
            print(json.dumps(data))
        else:
            print(
                _table(
                    [
                        ("stages ran", "stealth, stage0"),
                        (
                            "latency ms",
                            f"stage0={exc.stage0_ms:.1f} stealth={exc.stealth_ms:.1f}",
                        ),
                        (
                            "stealth",
                            f"{exc.stealth_status} ({exc.finding_count} findings)",
                        ),
                        ("judge", "No judge is enabled; no verdict was produced."),
                    ]
                )
            )
        return 3
    if args.json:
        print(response.model_dump_json(indent=2))
    else:
        print(_table(_response_rows(response)))
    return 0

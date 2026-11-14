"""Metrics over judged results (pass bar: <=5% clean flagged, >=80% violations caught)."""

import statistics
from typing import Final, Literal

from pydantic import BaseModel

from palimpsest.judge import PreparedCase
from palimpsest.schema import CaseResult, Verdict
from palimpsest.stealth.models import StealthStatus

MAX_CLEAN_FLAG_RATE: Final = 0.05
MIN_VIOLATION_RECALL: Final = 0.80
ADMIN_FLAG_STATUSES: Final = frozenset(
    {
        StealthStatus.CRITICAL_AI_POISONING,
        StealthStatus.CSS_CLOAKING_DETECTED,
        StealthStatus.HOMOGLYPH_SPOOFING,
    }
)
ADMIN_THRESHOLD: Final = 0.70
REVIEW_THRESHOLD: Final = 0.45
PARSE_ERROR_LABEL: Final = "PARSE_ERROR"
FLAGS: Final = frozenset(
    {Verdict.FLAG_G1_FACT, Verdict.FLAG_G2_FRAMING, Verdict.FLAG_G3_MOTIVE}
)


class Metrics(BaseModel):
    n: int
    labelled_n: int
    violation_recall: float
    category_accuracy: float
    clean_flag_rate: float
    abstain_rate: float
    parse_error_rate: float
    stage0_exit_rate: float
    stage0_false_pass: int
    source_unavailable_rate: float
    uncited_rate: float
    stealth_flag_rate: float
    stealth_flags: int
    admin_false_alarm_rate: float
    admin_recall: float
    review_rate: float
    unlabelled_admin: int
    unlabelled_review: int
    stage0_ms_p50: float
    stage1_ms_p50: float
    confusion: dict[str, dict[str, int]]
    passes_bar: bool


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _p50(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _verdict_label(result: CaseResult) -> str:
    return result.output.verdict.value if result.output else PARSE_ERROR_LABEL


def agreement(results_a: list[CaseResult], results_b: list[CaseResult]) -> float:
    """Share of shared case_ids, both parsed, with the same verdict."""
    by_id_b = {r.case_id: r for r in results_b}
    both = 0
    same = 0
    for a in results_a:
        b = by_id_b.get(a.case_id)
        if b is None or a.output is None or b.output is None:
            continue
        both += 1
        same += a.output.verdict == b.output.verdict
    return _ratio(same, both)


def _stealth_flagged(pc: PreparedCase) -> bool:
    return any(
        s.stealth_status != StealthStatus.CLEAN
        for s in (pc.diff_scan, pc.ref_scan)
        if s is not None
    )


def _diff_admin_flag(pc: PreparedCase) -> bool:
    return (
        pc.diff_scan is not None and pc.diff_scan.stealth_status in ADMIN_FLAG_STATUSES
    )


Route = Literal["admin", "review", "none"]


def route(result: CaseResult) -> Route:
    """Derived queue routing; the section 10 verdict itself is unchanged."""
    if result.stealth_status in {s.value for s in ADMIN_FLAG_STATUSES}:
        return "admin"
    if result.output is None or result.output.verdict not in FLAGS:
        return "none"
    if result.output.confidence >= ADMIN_THRESHOLD:
        return "admin"
    if result.output.confidence >= REVIEW_THRESHOLD:
        return "review"
    return "none"


def _score_model(prepared: list[PreparedCase], results: list[CaseResult]) -> Metrics:
    cases = {pc.case.case_id: pc for pc in prepared}
    paired = [(cases[r.case_id], r) for r in results if r.case_id in cases]
    violations = [
        (pc, r)
        for pc, r in paired
        if pc.case.expected in FLAGS and r.output is not None
    ]
    controls = [
        (pc, r)
        for pc, r in paired
        if pc.case.expected == Verdict.CLEAN_PASS and r.output is not None
    ]
    caught = sum(1 for _, r in violations if r.output and r.output.verdict in FLAGS)
    exact = sum(
        1 for pc, r in violations if r.output and r.output.verdict == pc.case.expected
    )
    clean_flagged = sum(
        1 for _, r in controls if r.output and r.output.verdict in FLAGS
    )
    judged = [r for _, r in paired if r.output is not None]
    abstained = sum(
        1 for r in judged if r.output and r.output.verdict == Verdict.EXPAND_CONTEXT
    )
    parse_errors = sum(1 for _, r in paired if r.output is None)
    stage1 = [r for _, r in paired if r.stage_reached >= 1]
    unavailable = sum(1 for r in stage1 if r.source_status == "unavailable")
    uncited = sum(1 for r in stage1 if r.source_status == "uncited")
    confusion: dict[str, dict[str, int]] = {}
    for pc, r in paired:
        if pc.case.expected == "UNLABELLED":
            continue
        row = confusion.setdefault(pc.case.expected.value, {})
        label = _verdict_label(r)
        row[label] = row.get(label, 0) + 1
    unlabelled = [r for pc, r in paired if pc.case.expected == "UNLABELLED"]
    recall = _ratio(caught, len(violations))
    clean_flag_rate = _ratio(clean_flagged, len(controls))
    return Metrics(
        n=len(paired),
        labelled_n=sum(1 for pc, _ in paired if pc.case.expected != "UNLABELLED"),
        violation_recall=recall,
        category_accuracy=_ratio(exact, len(violations)),
        clean_flag_rate=clean_flag_rate,
        abstain_rate=_ratio(abstained, len(paired)),
        parse_error_rate=_ratio(parse_errors, len(paired)),
        stage0_exit_rate=_ratio(sum(pc.stage0.clean for pc, _ in paired), len(paired)),
        stage0_false_pass=sum(
            1 for pc, _ in paired if pc.case.expected in FLAGS and pc.stage0.clean
        ),
        source_unavailable_rate=_ratio(unavailable, len(stage1)),
        uncited_rate=_ratio(uncited, len(stage1)),
        stealth_flag_rate=_ratio(
            sum(1 for pc, _ in paired if _stealth_flagged(pc)), len(paired)
        ),
        stealth_flags=sum(1 for pc, _ in paired if _diff_admin_flag(pc)),
        admin_false_alarm_rate=_ratio(
            sum(1 for _, r in controls if route(r) == "admin"), len(controls)
        ),
        admin_recall=_ratio(
            sum(1 for _, r in violations if route(r) == "admin"), len(violations)
        ),
        review_rate=_ratio(
            sum(1 for _, r in paired if route(r) == "review"), len(paired)
        ),
        unlabelled_admin=sum(1 for r in unlabelled if route(r) == "admin"),
        unlabelled_review=sum(1 for r in unlabelled if route(r) == "review"),
        stage0_ms_p50=_p50([r.stage0_ms for _, r in paired]),
        stage1_ms_p50=_p50([r.stage1_ms for r in stage1]),
        confusion=confusion,
        passes_bar=bool(violations)
        and bool(controls)
        and recall >= MIN_VIOLATION_RECALL
        and clean_flag_rate <= MAX_CLEAN_FLAG_RATE,
    )


def score(
    prepared: list[PreparedCase], results: dict[str, list[CaseResult]]
) -> dict[str, Metrics]:
    return {model: _score_model(prepared, rows) for model, rows in results.items()}

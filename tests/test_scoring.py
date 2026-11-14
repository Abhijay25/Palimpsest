from pathlib import Path

from palimpsest.judge import PreparedCase
from palimpsest.report import render_report
from palimpsest.schema import (
    AuditOutput,
    Case,
    CaseResult,
    ExpandDirection,
    ExpectedLabel,
    FlaggedSpan,
    Guideline,
    SourceWindow,
    Verdict,
)
from palimpsest.scoring import agreement, route, score
from palimpsest.stage0 import Stage0Result
from palimpsest.stealth.models import ScanResult, StealthStatus


def _prepared(
    case_id: str,
    expected: ExpectedLabel,
    new_text: str = "He admitted it.",
    stage0_clean: bool = False,
) -> PreparedCase:
    return PreparedCase(
        case=Case(
            case_id=case_id,
            lang="en",
            bucket="t",
            provenance="t",
            page_title="P",
            old_text="He said it.",
            new_text=new_text,
            ref_urls=[],
            expected=expected,
        ),
        stage0=Stage0Result(clean=stage0_clean, reasons=["r"], latency_ms=1.0),
        window=None
        if stage0_clean
        else SourceWindow(url=None, status="fixed", text="He said it.", latency_ms=0),
    )


def _output(verdict: Verdict, spans: list[FlaggedSpan] | None = None) -> AuditOutput:
    return AuditOutput(
        verdict=verdict,
        confidence=0.9,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=spans or [],
        neutral_rewrite=None,
    )


def _result(
    case_id: str, output: AuditOutput | None, error: str | None = None
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        model="m",
        prompt_version="stage2_v1",
        stage_reached=2,
        stage0_ms=1.0,
        stage1_ms=2.0,
        source_status="fixed",
        output=output,
        parse_error=error,
    )


def test_clean_flag_rate() -> None:
    prepared = [
        _prepared("a", Verdict.CLEAN_PASS),
        _prepared("b", Verdict.CLEAN_PASS),
    ]
    results = {
        "m": [
            _result("a", _output(Verdict.CLEAN_PASS)),
            _result("b", _output(Verdict.FLAG_G2_FRAMING)),
        ]
    }
    assert score(prepared, results)["m"].clean_flag_rate == 0.5


def test_recall_counts_wrong_category_as_caught() -> None:
    prepared = [
        _prepared("a", Verdict.FLAG_G1_FACT),
        _prepared("b", Verdict.FLAG_G2_FRAMING),
    ]
    results = {
        "m": [
            _result("a", _output(Verdict.FLAG_G3_MOTIVE)),
            _result("b", _output(Verdict.FLAG_G2_FRAMING)),
        ]
    }
    metrics = score(prepared, results)["m"]
    assert metrics.violation_recall == 1.0
    assert metrics.category_accuracy == 0.5


def test_parse_error_excluded_from_recall_denominator_but_counted() -> None:
    prepared = [
        _prepared("a", Verdict.FLAG_G1_FACT),
        _prepared("b", Verdict.FLAG_G1_FACT),
    ]
    results = {
        "m": [
            _result("a", _output(Verdict.FLAG_G1_FACT)),
            _result("b", None, error="bad json"),
        ]
    }
    metrics = score(prepared, results)["m"]
    assert metrics.violation_recall == 1.0
    assert metrics.parse_error_rate == 0.5


def test_stage0_false_pass_and_exit_rate() -> None:
    prepared = [
        _prepared("a", Verdict.FLAG_G1_FACT, stage0_clean=True),
        _prepared("b", Verdict.CLEAN_PASS),
    ]
    results = {
        "m": [
            _result("a", _output(Verdict.CLEAN_PASS)),
            _result("b", _output(Verdict.CLEAN_PASS)),
        ]
    }
    metrics = score(prepared, results)["m"]
    assert metrics.stage0_false_pass == 1
    assert metrics.stage0_exit_rate == 0.5
    assert not metrics.passes_bar


def test_agreement() -> None:
    a = [_result("a", _output(Verdict.CLEAN_PASS)), _result("b", None, "x")]
    b = [_result("a", _output(Verdict.CLEAN_PASS)), _result("b", None, "x")]
    assert agreement(a, b) == 1.0


def _report(tmp_path: Path, new_text: str, spans: list[FlaggedSpan]) -> str:
    prepared = [_prepared("a", Verdict.FLAG_G2_FRAMING, new_text=new_text)]
    results = {"m": [_result("a", _output(Verdict.FLAG_G2_FRAMING, spans))]}
    path = render_report(tmp_path, prepared, results, score(prepared, results))
    return path.read_text()


def test_report_escapes_html(tmp_path: Path) -> None:
    html = _report(tmp_path, "<script>alert(1)</script>", [])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_span_not_in_text_listed_not_crash(tmp_path: Path) -> None:
    span = FlaggedSpan(
        exact_substring="not present <b>",
        guideline_violated=Guideline.G2_FRAMING,
        explanation="why",
    )
    html = _report(tmp_path, "He admitted it.", [span])
    assert "not present &lt;b&gt;" in html
    assert "unmatched" in html.lower()


def test_span_highlighted_when_present(tmp_path: Path) -> None:
    span = FlaggedSpan(
        exact_substring="admitted",
        guideline_violated=Guideline.G2_FRAMING,
        explanation="why",
    )
    html = _report(tmp_path, "He admitted it.", [span])
    assert "<mark" in html


def test_uncited_rate() -> None:
    prepared = [_prepared("a", Verdict.CLEAN_PASS), _prepared("b", Verdict.CLEAN_PASS)]
    results = [
        _result("a", _output(Verdict.CLEAN_PASS)),
        _result("b", _output(Verdict.CLEAN_PASS)),
    ]
    results[0].source_status = "uncited"
    metrics = score(prepared, {"m": results})["m"]
    assert metrics.uncited_rate == 0.5
    assert metrics.source_unavailable_rate == 0.0


def test_stealth_flag_metrics() -> None:
    def scan(status: StealthStatus) -> ScanResult:
        return ScanResult(
            scan_id="s",
            target_type="WIKIPEDIA_DIFF",
            stealth_status=status,
            scan_latency_ms=1.0,
            sanitized_human_text="",
            hidden_findings=[],
        )

    prepared = [_prepared(c, Verdict.CLEAN_PASS) for c in "abcd"]
    prepared[0].diff_scan = scan(StealthStatus.CRITICAL_AI_POISONING)
    prepared[1].diff_scan = scan(StealthStatus.BENIGN_NOTES_ONLY)
    prepared[2].ref_scan = scan(StealthStatus.CRITICAL_AI_POISONING)
    prepared[3].diff_scan = scan(StealthStatus.CLEAN)
    results = {"m": [_result(c, _output(Verdict.CLEAN_PASS)) for c in "abcd"]}
    metrics = score(prepared, results)["m"]
    assert metrics.stealth_flags == 1
    assert metrics.stealth_flag_rate == 0.75


def _conf_result(
    case_id: str,
    verdict: Verdict,
    confidence: float,
    stealth_status: str | None = None,
) -> CaseResult:
    output = _output(verdict).model_copy(update={"confidence": confidence})
    result = _result(case_id, output)
    result.stealth_status = stealth_status
    return result


def test_route_boundaries() -> None:
    flag = Verdict.FLAG_G2_FRAMING
    assert route(_conf_result("a", flag, 0.70)) == "admin"
    assert route(_conf_result("a", flag, 0.69)) == "review"
    assert route(_conf_result("a", flag, 0.45)) == "review"
    assert route(_conf_result("a", flag, 0.44)) == "none"
    assert route(_conf_result("a", Verdict.CLEAN_PASS, 0.99)) == "none"
    assert route(_result("a", None, error="bad")) == "none"


def test_route_stealth_override() -> None:
    clean = Verdict.CLEAN_PASS
    for status in (
        "CRITICAL_AI_POISONING",
        "CSS_CLOAKING_DETECTED",
        "HOMOGLYPH_SPOOFING",
    ):
        assert route(_conf_result("a", clean, 0.1, status)) == "admin"
    assert route(_conf_result("a", clean, 0.1, "BENIGN_NOTES_ONLY")) == "none"
    assert route(_result("a", None, error="bad")) == "none"


def test_routing_metrics() -> None:
    prepared = [
        _prepared("c1", Verdict.CLEAN_PASS),
        _prepared("c2", Verdict.CLEAN_PASS),
        _prepared("v1", Verdict.FLAG_G1_FACT),
        _prepared("v2", Verdict.FLAG_G1_FACT),
        _prepared("u1", "UNLABELLED"),
        _prepared("u2", "UNLABELLED"),
    ]
    flag = Verdict.FLAG_G2_FRAMING
    results = {
        "m": [
            _conf_result("c1", flag, 0.75),
            _conf_result("c2", flag, 0.5),
            _conf_result("v1", flag, 0.9),
            _conf_result("v2", flag, 0.2),
            _conf_result("u1", flag, 0.8),
            _conf_result("u2", flag, 0.6),
        ]
    }
    m = score(prepared, results)["m"]
    assert m.admin_false_alarm_rate == 0.5
    assert m.admin_recall == 0.5
    assert m.review_rate == 2 / 6
    assert m.unlabelled_admin == 1
    assert m.unlabelled_review == 1

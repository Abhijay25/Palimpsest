import json
from pathlib import Path

from palimpsest.judge import (
    FileExchangeBackend,
    PreparedCase,
    render_case_payload,
)
from palimpsest.schema import AuditOutput, Case, SourceWindow, Verdict
from palimpsest.stage0 import Stage0Result

VALID_OUTPUT = {
    "verdict": "FLAG_G2_FRAMING",
    "confidence": 0.8,
    "expand_direction": "NONE",
    "atomic_propositions": [],
    "flagged_spans": [],
    "neutral_rewrite": "x",
}


def _case(case_id: str) -> Case:
    return Case(
        case_id=case_id,
        lang="en",
        bucket="t",
        provenance="t",
        page_title="P",
        old_text="He said it.",
        new_text="He admitted it.",
        ref_urls=[],
        expected=Verdict.FLAG_G2_FRAMING,
    )


def _prepared(case_id: str, clean: bool, status: str = "fixed") -> PreparedCase:
    window = SourceWindow(
        url=None,
        status="unavailable" if status == "unavailable" else "fixed",
        text="" if status == "unavailable" else "He said it on Monday.",
        latency_ms=0.0,
    )
    return PreparedCase(
        case=_case(case_id),
        stage0=Stage0Result(clean=clean, reasons=[], latency_ms=0.1),
        window=None if clean else window,
    )


def test_stage0_clean_cases_skip_batches(tmp_path: Path) -> None:
    paths = FileExchangeBackend().write_batches(
        [_prepared("a", clean=True)], tmp_path, ["haiku"]
    )
    assert paths == []


def test_batch_contains_prompt_and_payloads(tmp_path: Path) -> None:
    prepared = [_prepared("case_one", False), _prepared("case_two", False)]
    paths = FileExchangeBackend().write_batches(prepared, tmp_path, ["haiku"])
    assert len(paths) == 1
    text = paths[0].read_text()
    assert "CRITICAL GROUNDING RULE" in text
    assert "case_one" in text and "case_two" in text
    results_path = (tmp_path / "results" / "haiku" / "batch_001.jsonl").resolve()
    assert str(results_path) in text


def test_batches_skip_when_result_exists(tmp_path: Path) -> None:
    result = tmp_path / "results" / "haiku" / "batch_001.jsonl"
    result.parent.mkdir(parents=True)
    result.write_text("")
    paths = FileExchangeBackend().write_batches(
        [_prepared("a", False)], tmp_path, ["haiku"]
    )
    assert paths == []


def test_unavailable_source_payload_line() -> None:
    payload = render_case_payload(_prepared("a", False, status="unavailable"))
    assert "SOURCE UNAVAILABLE" in payload
    assert "judge framing from the diff only" in payload
    assert "DOMAIN_TRUST_TIER: UNKNOWN" in payload


def test_fixed_source_payload_has_window() -> None:
    payload = render_case_payload(_prepared("a", False))
    assert "He said it on Monday." in payload
    assert "SOURCE UNAVAILABLE" not in payload


def _write_result(tmp_path: Path, lines: list[str]) -> None:
    path = tmp_path / "results" / "haiku"
    path.mkdir(parents=True)
    (path / "batch_001.jsonl").write_text("\n".join(lines) + "\n")


def test_read_results_invalid_json_is_parse_error(tmp_path: Path) -> None:
    _write_result(tmp_path, ['{"case_id": "a", "output": {"verdict": "NOPE"}}'])
    results = FileExchangeBackend().read_results(tmp_path, "haiku")
    assert isinstance(results["a"], str)


def test_read_results_valid_line_parses(tmp_path: Path) -> None:
    _write_result(tmp_path, [json.dumps({"case_id": "a", "output": VALID_OUTPUT})])
    results = FileExchangeBackend().read_results(tmp_path, "haiku")
    out = results["a"]
    assert isinstance(out, AuditOutput)
    assert out.verdict == Verdict.FLAG_G2_FRAMING


def test_read_results_missing_dir_is_empty(tmp_path: Path) -> None:
    assert FileExchangeBackend().read_results(tmp_path, "haiku") == {}

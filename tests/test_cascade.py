import asyncio

from palimpsest.cascade import CascadeJudgeBackend
from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput, Case, Verdict
from palimpsest.stage0 import Stage0Result


def _output(verdict: Verdict, confidence: float) -> AuditOutput:
    return AuditOutput(
        verdict=verdict,
        confidence=confidence,
        expand_direction="NONE",
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )


def _case(case_id: str) -> PreparedCase:
    case = Case(
        case_id=case_id,
        lang="en",
        bucket="t",
        provenance="t",
        page_title="t",
        old_text="a",
        new_text="b",
        ref_urls=[],
        expected="UNLABELLED",
    )
    return PreparedCase(
        case=case,
        stage0=Stage0Result(clean=False, reasons=["x"], latency_ms=0.0),
        window=None,
    )


class FakeJudge:
    name = "fake"

    def __init__(self, model: str, answers: dict[str, AuditOutput | str]) -> None:
        self.model = model
        self.answers = answers
        self.latencies_ms: dict[str, float] = {}
        self.seen: list[str] = []

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        self.seen.extend(pc.case.case_id for pc in cases)
        self.latencies_ms.update({pc.case.case_id: 10.0 for pc in cases})
        return {pc.case.case_id: self.answers[pc.case.case_id] for pc in cases}


def test_only_flags_and_errors_reach_the_second_judge() -> None:
    first = FakeJudge(
        "small",
        {
            "clean": _output(Verdict.CLEAN_PASS, 0.6),
            "flag": _output(Verdict.FLAG_G2_FRAMING, 0.8),
            "broken": "parse error",
        },
    )
    second = FakeJudge(
        "big",
        {
            "flag": _output(Verdict.CLEAN_PASS, 0.7),
            "broken": _output(Verdict.FLAG_G1_FACT, 0.9),
        },
    )
    cascade = CascadeJudgeBackend(first, second)
    out = asyncio.run(cascade.judge([_case("clean"), _case("flag"), _case("broken")]))
    assert sorted(second.seen) == ["broken", "flag"]
    assert isinstance(out["flag"], AuditOutput)
    assert out["flag"].verdict == Verdict.CLEAN_PASS
    assert isinstance(out["broken"], AuditOutput)
    assert out["broken"].verdict == Verdict.FLAG_G1_FACT
    assert cascade.decided_by == {"clean": "small", "flag": "big", "broken": "big"}
    assert cascade.latencies_ms == {"clean": 10.0, "flag": 20.0, "broken": 20.0}
    assert cascade.model == "small->big"


def test_no_second_call_when_everything_is_clean() -> None:
    first = FakeJudge("small", {"a": _output(Verdict.CLEAN_PASS, 0.5)})
    second = FakeJudge("big", {})
    asyncio.run(CascadeJudgeBackend(first, second).judge([_case("a")]))
    assert second.seen == []


def test_cascade_judge_timed_keeps_per_call_state_local() -> None:
    first = FakeJudge("small", {"flag": _output(Verdict.FLAG_G2_FRAMING, 0.8)})
    second = FakeJudge("big", {"flag": _output(Verdict.CLEAN_PASS, 0.7)})
    cascade = CascadeJudgeBackend(first, second)
    results, latencies = asyncio.run(cascade.judge_timed([_case("flag")]))
    assert isinstance(results["flag"], AuditOutput)
    assert latencies == {"flag": 20.0}
    assert cascade.latencies_ms == {} and cascade.decided_by == {}
    # Sub-judge entries are consumed, so they do not accumulate either.
    assert first.latencies_ms == {} and second.latencies_ms == {}


def test_judge_with_latencies_pops_entries_of_plain_backends() -> None:
    from palimpsest.judge import judge_with_latencies

    judge = FakeJudge("small", {"a": _output(Verdict.CLEAN_PASS, 0.6)})
    _, latencies = asyncio.run(judge_with_latencies(judge, [_case("a")]))
    assert latencies == {"a": 10.0}
    assert judge.latencies_ms == {}

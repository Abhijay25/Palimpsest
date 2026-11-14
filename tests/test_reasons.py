import pytest

from palimpsest.reasons import reason_code, span_policy
from palimpsest.schema import AuditOutput, FlaggedSpan, SourceWindow, SpanType, Verdict


def _out(verdict: Verdict, spans: list[str]) -> AuditOutput:
    return AuditOutput(
        verdict=verdict,
        confidence=0.8,
        expand_direction="NONE",
        atomic_propositions=[],
        flagged_spans=[
            FlaggedSpan(
                exact_substring=s, guideline_violated="G2_FRAMING", explanation="x"
            )
            for s in spans
        ],
        neutral_rewrite=None,
    )


OLD = "The AP projected that she will advance. Critics disputed the figures."
NEW = "She advanced to the runoff."


def test_guideline_verdicts_map_directly() -> None:
    assert reason_code(_out(Verdict.FLAG_G1_FACT, []), OLD, NEW) == "CONTRADICTS_SOURCE"
    assert (
        reason_code(_out(Verdict.FLAG_G3_MOTIVE, []), OLD, NEW) == "UNSUPPORTED_CLAIM"
    )
    assert reason_code(_out(Verdict.CLEAN_PASS, []), OLD, NEW) is None
    assert reason_code(_out(Verdict.EXPAND_CONTEXT, []), OLD, NEW) is None


def test_removed_span_with_removal_mark_is_removed_context() -> None:
    out = _out(Verdict.FLAG_G2_FRAMING, ["The AP projected that (removed)"])
    assert reason_code(out, OLD, NEW) == "REMOVED_CONTEXT"


def test_added_wording_is_loaded_wording() -> None:
    out = _out(Verdict.FLAG_G2_FRAMING, ["advanced"])
    assert reason_code(
        out, "She went to the runoff.", "She advanced to the runoff."
    ) == ("LOADED_WORDING")


@pytest.mark.parametrize(
    ("span_type", "kind", "tier"),
    [
        (SpanType.CONTRADICTION, "FACT", "admin"),
        (SpanType.VALUE_CHANGE, "FACT", "admin"),
        (SpanType.REMOVED_QUALIFIER, "REMOVED_CONTEXT", "admin"),
        (SpanType.MOTIVE_CAUSE, "MOTIVE", "admin"),
        (SpanType.EVALUATIVE_LABEL, "FRAMING", "admin"),
        (SpanType.EDITORIAL_VOICE, "FRAMING", "admin"),
        (SpanType.NON_ENCYCLOPEDIC, "FRAMING", "admin"),
        (SpanType.SIZE_RANK_CLAIM, "FACT", "review"),
        (SpanType.INTENSIFIER, None, None),
        (SpanType.REGISTER, None, None),
    ],
)
def test_span_policy_covers_every_span_type(
    span_type: SpanType, kind: str | None, tier: str | None
) -> None:
    span = FlaggedSpan(
        exact_substring="one of the largest",
        guideline_violated="G2_FRAMING",
        explanation="x",
        span_type=span_type,
    )
    policy = span_policy(span, "admin", None)
    assert policy.kind == kind
    assert policy.tier == tier


def test_size_rank_claim_is_suppressed_when_the_source_states_it() -> None:
    span = FlaggedSpan(
        exact_substring="one of the largest",
        guideline_violated="G2_FRAMING",
        explanation="x",
        span_type=SpanType.SIZE_RANK_CLAIM,
    )
    window = SourceWindow(
        url=None,
        status="ok",
        text="It is one of the largest facilities in the region.",
        latency_ms=0.0,
    )
    assert span_policy(span, "admin", window).kind is None

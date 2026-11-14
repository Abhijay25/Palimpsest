from palimpsest.reasons import reason_code
from palimpsest.schema import AuditOutput, FlaggedSpan, Verdict


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

import pytest

from palimpsest.guided import (
    FreeFormConcern,
    GuidedAnswer,
    GuidedAnswers,
    SourceSupport,
    apply_value_swap_rule,
    guided_to_audit,
    validated_quote,
)
from palimpsest.schema import (
    AtomicProposition,
    AuditOutput,
    ClauseType,
    Entailment,
    ExpandDirection,
    Verdict,
)


def _answers(**changes: GuidedAnswer | bool | FreeFormConcern | None) -> GuidedAnswers:
    fields: dict[str, GuidedAnswer | bool | FreeFormConcern | None] = {
        "s1_value_swap": GuidedAnswer(yes=False),
        "s2_contentious_claim": GuidedAnswer(yes=False),
        "s3_added_motive": GuidedAnswer(yes=False),
        "s4_loaded_wording": GuidedAnswer(yes=False),
        "s5_certainty_shift": GuidedAnswer(yes=False),
        "s6_removed_context": GuidedAnswer(yes=False),
        "source_cut_off": False,
        "free_form_concern": None,
    }
    fields.update(changes)
    return GuidedAnswers.model_validate(fields)


def test_validated_quote_normalises_whitespace_but_not_case() -> None:
    assert validated_quote("alpha beta", "alpha\n beta") == "alpha\n beta"
    assert validated_quote("Alpha", "alpha") is None


@pytest.mark.parametrize(
    ("answer", "old", "new", "source", "verdict", "confidence"),
    [
        (
            _answers(
                s1_value_swap=GuidedAnswer(
                    yes=True,
                    old_quote="1997",
                    new_quote="2009",
                    source_quote="1997",
                    source_support=SourceSupport.OLD,
                )
            ),
            "The population was 1997.",
            "The population was 2009.",
            "The population was 1997.",
            Verdict.FLAG_G1_FACT,
            0.95,
        ),
        (
            _answers(
                s2_contentious_claim=GuidedAnswer(yes=True, new_quote="was arrested")
            ),
            "The person spoke.",
            "The person was arrested.",
            "The person spoke.",
            Verdict.FLAG_G1_FACT,
            0.85,
        ),
        (
            _answers(
                s3_added_motive=GuidedAnswer(yes=True, new_quote="to conceal fraud")
            ),
            "He attended.",
            "He attended to conceal fraud.",
            "He attended.",
            Verdict.FLAG_G3_MOTIVE,
            0.85,
        ),
        (
            _answers(
                s4_loaded_wording=GuidedAnswer(yes=True, new_quote="outrageously")
            ),
            "She spoke.",
            "She spoke outrageously.",
            "She spoke.",
            Verdict.FLAG_G2_FRAMING,
            0.8,
        ),
        (
            _answers(
                s5_certainty_shift=GuidedAnswer(
                    yes=True, old_quote="may be", new_quote="is"
                )
            ),
            "It may be true.",
            "It is true.",
            "It may be true.",
            Verdict.FLAG_G2_FRAMING,
            0.8,
        ),
        (
            _answers(
                s6_removed_context=GuidedAnswer(
                    yes=True,
                    old_quote="Critics said it was flawed.",
                    source_quote="Critics said it was flawed.",
                )
            ),
            "Critics said it was flawed.",
            "It was accepted.",
            "Critics said it was flawed.",
            Verdict.FLAG_G2_FRAMING,
            0.8,
        ),
    ],
)
def test_scenarios_choose_specified_verdict_and_confidence(
    answer: GuidedAnswers,
    old: str,
    new: str,
    source: str,
    verdict: Verdict,
    confidence: float,
) -> None:
    output = guided_to_audit(answer, old, new, source)
    assert output.verdict == verdict
    assert output.confidence == confidence
    assert output.flagged_spans


def test_edit_relative_quote_already_in_old_downgrades_to_review() -> None:
    output = guided_to_audit(
        _answers(
            s4_loaded_wording=GuidedAnswer(
                yes=True, new_quote="notorious", reason="Check loaded wording."
            )
        ),
        "The notorious person spoke.",
        "The notorious person spoke again.",
        "",
    )
    assert output.verdict == Verdict.FLAG_G2_FRAMING
    assert output.confidence == 0.65
    assert (
        output.flagged_spans[0].explanation
        == "Check loaded wording. Is this a concern?"
    )


def test_invalid_quote_downgrades_to_review_without_dropping_reason() -> None:
    output = guided_to_audit(
        _answers(
            s2_contentious_claim=GuidedAnswer(
                yes=True, new_quote="invented", reason="Possible harmful claim."
            )
        ),
        "The person spoke.",
        "The person was arrested.",
        "",
    )
    assert output.verdict == Verdict.FLAG_G2_FRAMING
    assert output.confidence == 0.65
    assert (
        output.flagged_spans[0].explanation
        == "Possible harmful claim. Is this a concern?"
    )


def test_free_form_concern_becomes_review_with_validated_quote() -> None:
    output = guided_to_audit(
        _answers(
            free_form_concern=FreeFormConcern(
                reason="Possible promotional wording.", quote="world-famous"
            )
        ),
        "The museum opened.",
        "The world-famous museum opened.",
        "",
    )
    assert output.verdict == Verdict.FLAG_G2_FRAMING
    assert output.confidence == 0.65
    assert output.flagged_spans[0].exact_substring == "world-famous"


def test_source_cut_off_expands_only_without_other_finding() -> None:
    answer = _answers(
        source_cut_off=True,
        s4_loaded_wording=GuidedAnswer(yes=True, new_quote="outrageously"),
    )
    output = guided_to_audit(answer, "She spoke.", "She spoke outrageously.", "")
    assert output.verdict == Verdict.FLAG_G2_FRAMING

    expanded = guided_to_audit(_answers(source_cut_off=True), "Old.", "New.", "")
    assert expanded.verdict == Verdict.EXPAND_CONTEXT
    assert expanded.expand_direction == ExpandDirection.BOTH


def test_mapping_to_audit_output_and_value_swap_review_rule() -> None:
    guided = guided_to_audit(
        _answers(s4_loaded_wording=GuidedAnswer(yes=True, new_quote="outrageously")),
        "She spoke.",
        "She spoke outrageously.",
        "",
    )
    assert isinstance(guided, AuditOutput)
    assert guided.flagged_spans[0].exact_substring == "outrageously"

    clean = AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[
            AtomicProposition(
                clause_text="The population was 2009.",
                clause_type=ClauseType.ACTION_FACT,
                source_entailment=Entailment.UNSUPPORTED_EXTRAPOLATION,
                evidence_quote_from_ref=None,
            )
        ],
        flagged_spans=[],
        neutral_rewrite=None,
    )
    output = apply_value_swap_rule(
        clean, "The population was 1997.", "The population was 2009."
    )
    assert output.verdict == Verdict.FLAG_G1_FACT
    assert output.confidence == 0.65
    assert output.flagged_spans[0].exact_substring == "2009"

import pytest

from palimpsest.guided import (
    FreeFormConcern,
    GuidedAnswer,
    GuidedAnswers,
    PolicyClass,
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
    ("answer", "old", "new", "source", "verdict", "confidence", "has_spans"),
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
            True,
        ),
        (
            _answers(
                s2_contentious_claim=GuidedAnswer(yes=True, new_quote="was arrested")
            ),
            "The person spoke.",
            "The person was arrested.",
            "The person spoke.",
            Verdict.FLAG_G1_FACT,
            0.8,
            True,
        ),
        (
            _answers(
                s3_added_motive=GuidedAnswer(yes=True, new_quote="to conceal fraud")
            ),
            "He attended.",
            "He attended to conceal fraud.",
            "He attended.",
            Verdict.CLEAN_PASS,
            1.0,
            False,
        ),
        (
            _answers(
                s4_loaded_wording=GuidedAnswer(yes=True, new_quote="outrageously")
            ),
            "She spoke.",
            "She spoke outrageously.",
            "She spoke.",
            Verdict.CLEAN_PASS,
            1.0,
            False,
        ),
        (
            _answers(
                s5_certainty_shift=GuidedAnswer(
                    yes=True,
                    old_quote="may be",
                    new_quote="is",
                    source_quote="may be",
                    source_support=SourceSupport.OLD,
                )
            ),
            "It may be true.",
            "It is true.",
            "It may be true.",
            Verdict.FLAG_G2_FRAMING,
            0.8,
            True,
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
            True,
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
    has_spans: bool,
) -> None:
    output = guided_to_audit(answer, old, new, source)
    assert output.verdict == verdict
    assert output.confidence == confidence
    assert bool(output.flagged_spans) is has_spans


def test_edit_relative_quote_already_in_old_is_not_a_signal() -> None:
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
    assert output.verdict == Verdict.CLEAN_PASS
    assert output.flagged_spans == []


def test_invalid_quote_is_not_a_signal() -> None:
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
    assert output.verdict == Verdict.CLEAN_PASS
    assert output.flagged_spans == []


def test_free_form_concern_is_a_weak_note_with_validated_quote() -> None:
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
    assert output.verdict == Verdict.CLEAN_PASS
    assert output.flagged_spans == []
    assert output.atomic_propositions[0].clause_text.startswith("Checklist note:")


def test_source_cut_off_expands_only_without_other_finding() -> None:
    answer = _answers(
        source_cut_off=True,
        s4_loaded_wording=GuidedAnswer(yes=True, new_quote="outrageously"),
    )
    output = guided_to_audit(answer, "She spoke.", "She spoke outrageously.", "")
    assert output.verdict == Verdict.EXPAND_CONTEXT

    expanded = guided_to_audit(_answers(source_cut_off=True), "Old.", "New.", "")
    assert expanded.verdict == Verdict.EXPAND_CONTEXT
    assert expanded.expand_direction == ExpandDirection.BOTH


def test_s1_supported_new_value_is_not_a_finding() -> None:
    output = guided_to_audit(
        _answers(
            s1_value_swap=GuidedAnswer(
                yes=True,
                old_quote="2024-25",
                new_quote="2025-26",
                source_quote="2025-26",
                source_support=SourceSupport.NEW,
            )
        ),
        "The season was 2024-25.",
        "The season was 2025-26.",
        "The season was 2025-26.",
    )
    assert output.verdict == Verdict.CLEAN_PASS
    assert output.flagged_spans == []


def test_s1_without_source_support_is_a_weak_note() -> None:
    output = guided_to_audit(
        _answers(
            s1_value_swap=GuidedAnswer(yes=True, old_quote="1997", new_quote="2009")
        ),
        "The population was 1997.",
        "The population was 2009.",
        "The population is unknown.",
    )
    assert output.verdict == Verdict.CLEAN_PASS
    assert len(output.atomic_propositions) == 1


def test_two_weak_signals_on_one_sentence_route_to_review() -> None:
    output = guided_to_audit(
        _answers(
            s3_added_motive=GuidedAnswer(yes=True, new_quote="to conceal fraud"),
            s4_loaded_wording=GuidedAnswer(yes=True, new_quote="shamefully"),
        ),
        "He attended.",
        "He shamefully attended to conceal fraud.",
        "He attended.",
    )
    assert output.verdict == Verdict.FLAG_G3_MOTIVE
    assert output.confidence == 0.65
    assert len(output.flagged_spans) == 2


def test_policy_do_not_flag_wording_is_weakest() -> None:
    output = guided_to_audit(
        _answers(
            s4_loaded_wording=GuidedAnswer(
                yes=True,
                new_quote="fiercely",
                policy_class=PolicyClass.DO_NOT_FLAG,
            )
        ),
        "The teams competed.",
        "The teams competed fiercely.",
        "The teams competed.",
    )
    assert output.verdict == Verdict.CLEAN_PASS
    assert output.flagged_spans == []
    assert output.atomic_propositions == []


def test_mapping_to_audit_output_and_value_swap_review_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALIMPSEST_VALUE_SWAP_REVIEW", "1")
    guided = guided_to_audit(
        _answers(s2_contentious_claim=GuidedAnswer(yes=True, new_quote="was arrested")),
        "The person spoke.",
        "The person was arrested.",
        "",
    )
    assert isinstance(guided, AuditOutput)
    assert guided.flagged_spans[0].exact_substring == "was arrested"

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


def test_value_swap_rule_limits_replace_operations_and_summarises_extra_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALIMPSEST_VALUE_SWAP_REVIEW", "1")
    clean = AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[
            AtomicProposition(
                clause_text="Epsilon Zeta Eta Theta.",
                clause_type=ClauseType.ACTION_FACT,
                source_entailment=Entailment.UNSUPPORTED_EXTRAPOLATION,
                evidence_quote_from_ref=None,
            )
        ],
        flagged_spans=[],
        neutral_rewrite=None,
    )
    output = apply_value_swap_rule(
        clean,
        "One Alpha. Two Beta. Three Gamma. Four Delta.",
        "One Epsilon. Two Zeta. Three Eta. Four Theta.",
    )
    assert len(output.flagged_spans) == 3
    assert output.flagged_spans[-1].explanation.endswith("and 1 more changed values")


def test_value_swap_rule_emits_one_flag_for_a_replace_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALIMPSEST_VALUE_SWAP_REVIEW", "1")
    clean = AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[
            AtomicProposition(
                clause_text="Gamma Delta 2009.",
                clause_type=ClauseType.ACTION_FACT,
                source_entailment=Entailment.UNSUPPORTED_EXTRAPOLATION,
                evidence_quote_from_ref=None,
            )
        ],
        flagged_spans=[],
        neutral_rewrite=None,
    )
    output = apply_value_swap_rule(
        clean,
        "The records Alpha Beta 1997.",
        "The records Gamma Delta 2009.",
    )
    assert len(output.flagged_spans) == 1
    assert output.flagged_spans[0].exact_substring == "Gamma"
    assert output.flagged_spans[0].explanation.endswith("and 2 more changed values")


def test_value_swap_rule_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALIMPSEST_VALUE_SWAP_REVIEW", raising=False)
    clean = AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )
    assert apply_value_swap_rule(clean, "Population 1997.", "Population 2009.") == clean


def test_guided_schema_is_accepted_by_gemini_response_schema() -> None:
    # Gemini's response_schema rejects additionalProperties (live 400 INVALID_ARGUMENT).
    import json

    from palimpsest.guided import GuidedAnswers

    assert "additionalProperties" not in json.dumps(GuidedAnswers.model_json_schema())

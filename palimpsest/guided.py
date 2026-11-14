"""Validation and deterministic decision logic for the stage2_v9 checklist."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from palimpsest.schema import (
    AuditOutput,
    Entailment,
    ExpandDirection,
    FlaggedSpan,
    Guideline,
    Verdict,
)
from palimpsest.value_swaps import swaps


class SourceSupport(StrEnum):
    OLD = "OLD"
    NEW = "NEW"
    NEITHER = "NEITHER"


class GuidedAnswer(BaseModel):
    """One checklist response; unused quotes are null."""

    model_config = ConfigDict(extra="forbid")

    yes: bool
    old_quote: str | None = None
    new_quote: str | None = None
    source_quote: str | None = None
    source_support: SourceSupport = SourceSupport.NEITHER
    reason: str = Field(default="", max_length=500)


class FreeFormConcern(BaseModel):
    """An out-of-checklist concern, with an optional quote from the edit."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    quote: str | None = Field(default=None, max_length=500)


class GuidedAnswers(BaseModel):
    """The deliberately narrow response schema used by the v9 Gemini request."""

    model_config = ConfigDict(extra="forbid")

    s1_value_swap: GuidedAnswer
    s2_contentious_claim: GuidedAnswer
    s3_added_motive: GuidedAnswer
    s4_loaded_wording: GuidedAnswer
    s5_certainty_shift: GuidedAnswer
    s6_removed_context: GuidedAnswer
    source_cut_off: bool
    free_form_concern: FreeFormConcern | None = None


_SPACE = re.compile(r"\s+")


def _normalised(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def validated_quote(quote: str | None, text: str) -> str | None:
    """Return the source spelling of a whitespace-normalised exact substring."""
    if not quote or not _normalised(quote):
        return None
    pieces = [re.escape(piece) for piece in _normalised(quote).split(" ")]
    match = re.search(r"\s+".join(pieces), text)
    return match.group(0) if match else None


def _new_quote(answer: GuidedAnswer, old: str, new: str) -> str | None:
    quote = validated_quote(answer.new_quote, new)
    return quote if quote is not None and validated_quote(quote, old) is None else None


def _old_quote(
    answer: GuidedAnswer, old: str, new: str, *, require_removed: bool = False
) -> str | None:
    quote = validated_quote(answer.old_quote, old)
    if quote is None:
        return None
    if require_removed and validated_quote(quote, new) is not None:
        return None
    return quote


def _source_quote(answer: GuidedAnswer, source: str) -> str | None:
    return validated_quote(answer.source_quote, source)


def _supplied_quotes_validate(
    answer: GuidedAnswer, old: str, new: str, source: str
) -> bool:
    """Every supplied model quote must be grounded, even if optional."""
    return (
        (answer.old_quote is None or validated_quote(answer.old_quote, old) is not None)
        and (
            answer.new_quote is None
            or validated_quote(answer.new_quote, new) is not None
        )
        and (
            answer.source_quote is None
            or validated_quote(answer.source_quote, source) is not None
        )
    )


def _reason(answer: GuidedAnswer, fallback: str) -> str:
    return answer.reason.strip() or fallback


def _span(quote: str, guideline: Guideline, explanation: str) -> FlaggedSpan:
    return FlaggedSpan(
        exact_substring=quote, guideline_violated=guideline, explanation=explanation
    )


def _review_reason(reason: str) -> str:
    """Keep the model's concern while making its lower-tier route actionable."""
    return reason if reason.rstrip().endswith("?") else f"{reason} Is this a concern?"


def _mentions_swap(old_quote: str, new_quote: str, old: str, new: str) -> bool:
    """Require a reported S1 pair to agree with the independent value detector."""
    return any(
        any(value in old_quote for value in old_values)
        and any(value in new_quote for value in new_values)
        for old_values, new_values in swaps(old, new)
    )


def _review_output(
    reason: str, quote: str | None, guideline: Guideline = Guideline.G2_FRAMING
) -> AuditOutput:
    anchor = quote or ""
    spans = [_span(anchor, guideline, _review_reason(reason))]
    return AuditOutput(
        verdict=Verdict.FLAG_G2_FRAMING,
        confidence=0.65,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=spans,
        neutral_rewrite=None,
    )


def guided_to_audit(
    answers: GuidedAnswers, old_text: str, new_text: str, source_text: str
) -> AuditOutput:
    """Validate a guided response and produce the unchanged public audit contract."""
    failed: list[tuple[str, str | None]] = []
    findings: list[tuple[Verdict, float, FlaggedSpan]] = []

    s1 = answers.s1_value_swap
    if s1.yes:
        old_quote, new_quote = (
            _old_quote(s1, old_text, new_text, require_removed=True),
            _new_quote(s1, old_text, new_text),
        )
        source_quote = _source_quote(s1, source_text)
        valid = _supplied_quotes_validate(s1, old_text, new_text, source_text)
        valid = valid and old_quote is not None and new_quote is not None
        if s1.source_support != SourceSupport.NEITHER:
            valid = valid and source_quote is not None
        valid = (
            valid
            and old_quote is not None
            and new_quote is not None
            and _mentions_swap(old_quote, new_quote, old_text, new_text)
        )
        if not valid:
            failed.append(
                (_reason(s1, "Possible value change needs review."), new_quote)
            )
        elif s1.source_support != SourceSupport.NEW:
            assert old_quote is not None and new_quote is not None
            detail = (
                f"The edit changes {old_quote} to {new_quote}; the cited source gives "
                f"{source_quote}."
                if source_quote
                else f"The edit changes {old_quote} to {new_quote}; can the source confirm it?"
            )
            findings.append(
                (
                    Verdict.FLAG_G1_FACT,
                    0.95 if source_quote else 0.65,
                    _span(new_quote, Guideline.G1_FACT, detail),
                )
            )

    s2 = answers.s2_contentious_claim
    if s2.yes:
        quote, source_quote = (
            _new_quote(s2, old_text, new_text),
            _source_quote(s2, source_text),
        )
        valid = _supplied_quotes_validate(s2, old_text, new_text, source_text)
        valid = (
            valid
            and quote is not None
            and (s2.source_support == SourceSupport.NEITHER or source_quote is not None)
        )
        if not valid:
            failed.append(
                (_reason(s2, "Possible contentious claim needs review."), quote)
            )
        elif s2.source_support == SourceSupport.NEITHER:
            assert quote is not None
            findings.append(
                (
                    Verdict.FLAG_G1_FACT,
                    0.85,
                    _span(
                        quote,
                        Guideline.G1_FACT,
                        f"The source does not state this contentious claim: {quote}.",
                    ),
                )
            )

    s3 = answers.s3_added_motive
    if s3.yes:
        quote, source_quote = (
            _new_quote(s3, old_text, new_text),
            _source_quote(s3, source_text),
        )
        valid = _supplied_quotes_validate(s3, old_text, new_text, source_text)
        valid = (
            valid
            and quote is not None
            and (s3.source_support == SourceSupport.NEITHER or source_quote is not None)
        )
        if not valid:
            failed.append(
                (_reason(s3, "Possible unsupported motive needs review."), quote)
            )
        elif s3.source_support == SourceSupport.NEITHER:
            assert quote is not None
            findings.append(
                (
                    Verdict.FLAG_G3_MOTIVE,
                    0.85,
                    _span(
                        quote,
                        Guideline.G3_MOTIVE,
                        f"The source does not state this added motive: {quote}.",
                    ),
                )
            )

    s4 = answers.s4_loaded_wording
    if s4.yes:
        quote = _new_quote(s4, old_text, new_text)
        if quote is None or not _supplied_quotes_validate(
            s4, old_text, new_text, source_text
        ):
            failed.append((_reason(s4, "Possible loaded wording needs review."), None))
        else:
            findings.append(
                (
                    Verdict.FLAG_G2_FRAMING,
                    0.8,
                    _span(
                        quote,
                        Guideline.G2_FRAMING,
                        f"The edit adds loaded wording: {quote}.",
                    ),
                )
            )

    s5 = answers.s5_certainty_shift
    if s5.yes:
        old_quote, new_quote = (
            _old_quote(s5, old_text, new_text),
            _new_quote(s5, old_text, new_text),
        )
        if (
            old_quote is None
            or new_quote is None
            or not _supplied_quotes_validate(s5, old_text, new_text, source_text)
        ):
            failed.append(
                (_reason(s5, "Possible certainty shift needs review."), new_quote)
            )
        else:
            findings.append(
                (
                    Verdict.FLAG_G2_FRAMING,
                    0.8,
                    _span(
                        new_quote,
                        Guideline.G2_FRAMING,
                        f"The edit changes {old_quote} to {new_quote}, increasing "
                        "certainty or changing attribution.",
                    ),
                )
            )

    s6 = answers.s6_removed_context
    if s6.yes:
        quote, source_quote = (
            _old_quote(s6, old_text, new_text, require_removed=True),
            _source_quote(s6, source_text),
        )
        if (
            quote is None
            or source_quote is None
            or not _supplied_quotes_validate(s6, old_text, new_text, source_text)
        ):
            failed.append(
                (_reason(s6, "Possible removed context needs review."), quote)
            )
        else:
            findings.append(
                (
                    Verdict.FLAG_G2_FRAMING,
                    0.8,
                    _span(
                        quote,
                        Guideline.G2_FRAMING,
                        f"The edit removes sourced context: {quote}.",
                    ),
                )
            )

    if failed:
        reason, quote = failed[0]
        return _review_output(reason, quote)
    concern = answers.free_form_concern
    if concern is not None:
        quote = _new_quote(
            GuidedAnswer(yes=True, new_quote=concern.quote), old_text, new_text
        )
        return _review_output(concern.reason.strip(), quote)
    if findings:
        severity = {
            Verdict.FLAG_G1_FACT: 3,
            Verdict.FLAG_G3_MOTIVE: 2,
            Verdict.FLAG_G2_FRAMING: 1,
        }
        verdict, confidence, _span_for_verdict = max(
            findings, key=lambda item: severity[item[0]]
        )
        return AuditOutput(
            verdict=verdict,
            confidence=confidence,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=[],
            flagged_spans=[finding[2] for finding in findings],
            neutral_rewrite=None,
        )
    if answers.source_cut_off:
        return AuditOutput(
            verdict=Verdict.EXPAND_CONTEXT,
            confidence=0.0,
            expand_direction=ExpandDirection.BOTH,
            atomic_propositions=[],
            flagged_spans=[],
            neutral_rewrite=None,
        )
    return AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )


def apply_value_swap_rule(
    output: AuditOutput, old_text: str, new_text: str
) -> AuditOutput:
    """Escalate unsupported clean-pass value replacements to the review queue."""
    if output.verdict != Verdict.CLEAN_PASS:
        return output
    new_values = {
        value for _, replacements in swaps(old_text, new_text) for value in replacements
    }
    unsupported = [
        proposition
        for proposition in output.atomic_propositions
        if proposition.source_entailment
        in {Entailment.UNSUPPORTED_EXTRAPOLATION, Entailment.CONTRADICTED}
    ]
    spans: list[FlaggedSpan] = []
    for old_values, replacements in swaps(old_text, new_text):
        for replacement in sorted(replacements):
            if replacement not in new_values or not any(
                replacement in proposition.clause_text for proposition in unsupported
            ):
                continue
            old_value = min(old_values)
            spans.append(
                _span(
                    replacement,
                    Guideline.G1_FACT,
                    "VALUE_CHANGED: The edit changes "
                    f"{old_value} to {replacement}; the cited source does not state "
                    f"the new value. Is this a correction?",
                )
            )
    if not spans:
        return output
    return AuditOutput(
        verdict=Verdict.FLAG_G1_FACT,
        confidence=0.65,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=output.atomic_propositions,
        flagged_spans=spans,
        neutral_rewrite=None,
    )

"""Validation and deterministic decision logic for the stage2_v9 checklist."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

from palimpsest.schema import (
    AtomicProposition,
    AuditOutput,
    ClauseType,
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


class PolicyClass(StrEnum):
    """Whether a wording response is excluded by the flag policy."""

    SUBSTANTIVE = "SUBSTANTIVE"
    DO_NOT_FLAG = "DO_NOT_FLAG"


class EvidenceWeight(StrEnum):
    """Evidence strength used by the deterministic v9 aggregation."""

    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"
    WEAKEST = "WEAKEST"


class GuidedAnswer(BaseModel):
    """One checklist response; unused quotes are null."""

    yes: bool
    old_quote: str | None = None
    new_quote: str | None = None
    source_quote: str | None = None
    source_support: SourceSupport = SourceSupport.NEITHER
    policy_class: PolicyClass = PolicyClass.SUBSTANTIVE
    reason: str = Field(default="", max_length=500)


class FreeFormConcern(BaseModel):
    """An out-of-checklist concern, with an optional quote from the edit."""

    reason: str = Field(min_length=1, max_length=500)
    quote: str | None = Field(default=None, max_length=500)


class GuidedAnswers(BaseModel):
    """The deliberately narrow response schema used by the v9 Gemini request."""

    s1_value_swap: GuidedAnswer
    s2_contentious_claim: GuidedAnswer
    s3_added_motive: GuidedAnswer
    s4_loaded_wording: GuidedAnswer
    s5_certainty_shift: GuidedAnswer
    s6_removed_context: GuidedAnswer
    source_cut_off: bool
    free_form_concern: FreeFormConcern | None = None


_SPACE = re.compile(r"\s+")
_SENTENCE_BOUNDARY = re.compile(r"[.!?](?=\s|$)")


@dataclass(frozen=True)
class _Signal:
    """A fully grounded checklist observation before route aggregation."""

    weight: EvidenceWeight
    verdict: Verdict
    guideline: Guideline
    quote: str | None
    explanation: str
    unit: str


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
        old_value in old_quote and new_value in new_quote
        for change in swaps(old, new)
        for old_value, new_value in change.pairs
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


def _unit_for(quote: str | None, text: str, fallback: str) -> str:
    """Group evidence by the sentence that contains its validated anchor."""
    if quote is None:
        return fallback
    start = text.find(quote)
    if start < 0:
        return fallback
    previous = 0
    for boundary in _SENTENCE_BOUNDARY.finditer(text):
        if start <= boundary.start():
            return _normalised(text[previous : boundary.end()])
        previous = boundary.end()
    return _normalised(text[previous:]) or fallback


def _signal(
    weight: EvidenceWeight,
    verdict: Verdict,
    guideline: Guideline,
    quote: str | None,
    explanation: str,
    text: str,
    fallback: str,
) -> _Signal:
    return _Signal(
        weight=weight,
        verdict=verdict,
        guideline=guideline,
        quote=quote,
        explanation=explanation,
        unit=_unit_for(quote, text, fallback),
    )


def _note_for(signal: _Signal) -> AtomicProposition:
    clause_type = {
        Guideline.G1_FACT: ClauseType.ACTION_FACT,
        Guideline.G2_FRAMING: ClauseType.FRAMING_MODALITY,
        Guideline.G3_MOTIVE: ClauseType.MOTIVE_CAUSE,
    }[signal.guideline]
    return AtomicProposition(
        clause_text=f"Checklist note: {signal.explanation}",
        clause_type=clause_type,
        source_entailment=Entailment.AMBIGUOUS_CONTEXT,
        evidence_quote_from_ref=None,
    )


def _audit_for_signals(signals: list[_Signal], source_cut_off: bool) -> AuditOutput:
    """Route only independently validated evidence at its prescribed weight."""
    strong_or_medium = [
        signal
        for signal in signals
        if signal.weight in {EvidenceWeight.STRONG, EvidenceWeight.MEDIUM}
    ]
    if strong_or_medium:
        highest = (
            EvidenceWeight.STRONG
            if any(s.weight == EvidenceWeight.STRONG for s in strong_or_medium)
            else EvidenceWeight.MEDIUM
        )
        selected = strong_or_medium
        confidence = 0.95 if highest == EvidenceWeight.STRONG else 0.80
        verdict = max(
            selected,
            key=lambda signal: {
                Verdict.FLAG_G1_FACT: 3,
                Verdict.FLAG_G3_MOTIVE: 2,
                Verdict.FLAG_G2_FRAMING: 1,
            }[signal.verdict],
        ).verdict
        return AuditOutput(
            verdict=verdict,
            confidence=confidence,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=[
                _note_for(signal)
                for signal in signals
                if signal.weight == EvidenceWeight.WEAK
            ],
            flagged_spans=[
                _span(signal.quote or "", signal.guideline, signal.explanation)
                for signal in selected
            ],
            neutral_rewrite=None,
        )
    weak_by_unit: dict[str, list[_Signal]] = {}
    for signal in signals:
        if signal.weight == EvidenceWeight.WEAK:
            weak_by_unit.setdefault(signal.unit, []).append(signal)
    selected_weak = next(
        (
            unit_signals
            for unit_signals in weak_by_unit.values()
            if len(unit_signals) >= 2
        ),
        None,
    )
    if selected_weak is not None:
        verdict = max(
            selected_weak,
            key=lambda signal: {
                Verdict.FLAG_G1_FACT: 3,
                Verdict.FLAG_G3_MOTIVE: 2,
                Verdict.FLAG_G2_FRAMING: 1,
            }[signal.verdict],
        ).verdict
        return AuditOutput(
            verdict=verdict,
            confidence=0.65,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=[],
            flagged_spans=[
                _span(
                    signal.quote or "",
                    signal.guideline,
                    _review_reason(signal.explanation),
                )
                for signal in selected_weak
            ],
            neutral_rewrite=None,
        )
    weak_notes = [
        _note_for(signal) for signal in signals if signal.weight == EvidenceWeight.WEAK
    ]
    if source_cut_off:
        return AuditOutput(
            verdict=Verdict.EXPAND_CONTEXT,
            confidence=0.0,
            expand_direction=ExpandDirection.BOTH,
            atomic_propositions=weak_notes,
            flagged_spans=[],
            neutral_rewrite=None,
        )
    return AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=weak_notes,
        flagged_spans=[],
        neutral_rewrite=None,
    )


def guided_to_audit(
    answers: GuidedAnswers, old_text: str, new_text: str, source_text: str
) -> AuditOutput:
    """Validate a guided response and produce the unchanged public audit contract."""
    signals: list[_Signal] = []

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
        if valid and s1.source_support != SourceSupport.NEW:
            assert old_quote is not None and new_quote is not None
            detail = (
                f"The edit changes {old_quote} to {new_quote}; the cited source gives "
                f"{source_quote}."
                if source_quote
                else f"The edit changes {old_quote} to {new_quote}; can the source confirm it?"
            )
            signals.append(
                _signal(
                    EvidenceWeight.STRONG
                    if s1.source_support == SourceSupport.OLD
                    else EvidenceWeight.WEAK,
                    Verdict.FLAG_G1_FACT,
                    Guideline.G1_FACT,
                    new_quote,
                    detail,
                    new_text,
                    "s1_value_swap",
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
        if valid and s2.source_support == SourceSupport.NEITHER:
            assert quote is not None
            signals.append(
                _signal(
                    EvidenceWeight.MEDIUM,
                    Verdict.FLAG_G1_FACT,
                    Guideline.G1_FACT,
                    quote,
                    f"The source does not state this contentious claim: {quote}.",
                    new_text,
                    "s2_contentious_claim",
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
        if valid and s3.source_support == SourceSupport.NEITHER:
            assert quote is not None
            signals.append(
                _signal(
                    EvidenceWeight.WEAK,
                    Verdict.FLAG_G3_MOTIVE,
                    Guideline.G3_MOTIVE,
                    quote,
                    f"The source does not state this added motive: {quote}.",
                    new_text,
                    "s3_added_motive",
                )
            )

    s4 = answers.s4_loaded_wording
    if s4.yes:
        quote = _new_quote(s4, old_text, new_text)
        if quote is not None and _supplied_quotes_validate(
            s4, old_text, new_text, source_text
        ):
            signals.append(
                _signal(
                    EvidenceWeight.WEAKEST
                    if s4.policy_class == PolicyClass.DO_NOT_FLAG
                    else EvidenceWeight.WEAK,
                    Verdict.FLAG_G2_FRAMING,
                    Guideline.G2_FRAMING,
                    quote,
                    f"The edit adds loaded wording: {quote}.",
                    new_text,
                    "s4_loaded_wording",
                )
            )

    s5 = answers.s5_certainty_shift
    if s5.yes:
        old_quote, new_quote = (
            _old_quote(s5, old_text, new_text),
            _new_quote(s5, old_text, new_text),
        )
        source_quote = _source_quote(s5, source_text)
        valid = (
            old_quote is not None
            and new_quote is not None
            and _supplied_quotes_validate(s5, old_text, new_text, source_text)
            and (s5.source_support == SourceSupport.NEITHER or source_quote is not None)
        )
        if valid and s5.source_support != SourceSupport.NEW:
            assert old_quote is not None and new_quote is not None
            signals.append(
                _signal(
                    EvidenceWeight.MEDIUM
                    if s5.source_support == SourceSupport.OLD
                    else EvidenceWeight.WEAK,
                    Verdict.FLAG_G2_FRAMING,
                    Guideline.G2_FRAMING,
                    new_quote,
                    f"The edit changes {old_quote} to {new_quote}, increasing "
                    "certainty or changing attribution.",
                    new_text,
                    "s5_certainty_shift",
                )
            )

    s6 = answers.s6_removed_context
    if s6.yes:
        quote, source_quote = (
            _old_quote(s6, old_text, new_text, require_removed=True),
            _source_quote(s6, source_text),
        )
        if (
            quote is not None
            and source_quote is not None
            and _supplied_quotes_validate(s6, old_text, new_text, source_text)
        ):
            signals.append(
                _signal(
                    EvidenceWeight.MEDIUM,
                    Verdict.FLAG_G2_FRAMING,
                    Guideline.G2_FRAMING,
                    quote,
                    f"The edit removes sourced context: {quote}.",
                    old_text,
                    "s6_removed_context",
                )
            )

    concern = answers.free_form_concern
    if concern is not None:
        quote = _new_quote(
            GuidedAnswer(yes=True, new_quote=concern.quote), old_text, new_text
        )
        signals.append(
            _signal(
                EvidenceWeight.WEAK,
                Verdict.FLAG_G2_FRAMING,
                Guideline.G2_FRAMING,
                quote,
                concern.reason.strip(),
                new_text,
                "free_form_concern",
            )
        )
    return _audit_for_signals(signals, answers.source_cut_off)


def apply_value_swap_rule(
    output: AuditOutput,
    old_text: str,
    new_text: str,
    citation_backed_claim: Callable[[str], bool] | None = None,
) -> AuditOutput:
    """Escalate unsupported clean-pass value replacements to the review queue."""
    if (
        os.environ.get("PALIMPSEST_VALUE_SWAP_REVIEW") != "1"
        or output.verdict != Verdict.CLEAN_PASS
    ):
        return output
    unsupported = [
        proposition
        for proposition in output.atomic_propositions
        if proposition.source_entailment
        in {Entailment.UNSUPPORTED_EXTRAPOLATION, Entailment.CONTRADICTED}
    ]
    matched: list[tuple[str, str, int]] = []
    for change in swaps(old_text, new_text):
        pairs = [
            pair
            for pair in change.pairs
            if any(pair[1] in proposition.clause_text for proposition in unsupported)
        ]
        if pairs:
            old_value, replacement = pairs[0]
            if citation_backed_claim is not None and citation_backed_claim(replacement):
                continue
            matched.append((old_value, replacement, len(pairs)))
    spans: list[FlaggedSpan] = []
    for old_value, replacement, _ in matched[:3]:
        spans.append(
            _span(
                replacement,
                Guideline.G1_FACT,
                "VALUE_CHANGED: The edit changes "
                f"{old_value} to {replacement}; the cited source does not state "
                f"the new value. Is this a correction?",
            )
        )
    extra = sum(count for _, _, count in matched) - len(spans)
    if extra:
        last = spans[-1]
        spans[-1] = last.model_copy(
            update={
                "explanation": f"{last.explanation} and {extra} more changed values"
            }
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

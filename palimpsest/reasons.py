"""Descriptive reason code for a flagged edit, derived without extra model calls.

The judge's verdict says which guideline was broken; the diff says whether the
flagged text was added or removed. Intent (manipulation vs good-faith update)
is not inferred: it cannot be read reliably from a diff (session-2 finding).
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from palimpsest.schema import AuditOutput, FlaggedSpan, FlagKind, FlagTier, SourceWindow

ReasonCode = Literal[
    "CONTRADICTS_SOURCE",
    "UNSUPPORTED_CLAIM",
    "LOADED_WORDING",
    "REMOVED_CONTEXT",
    "CITATION_DATE",
    "VALUE_CHANGED",
]

REASON_TEXT: Final[dict[ReasonCode, str]] = {
    "CONTRADICTS_SOURCE": "A fact in the edit differs from the cited source; check "
    "whether the source is outdated or the edit is wrong.",
    "UNSUPPORTED_CLAIM": "The edit adds a purpose, cause or claim the cited source "
    "does not state.",
    "LOADED_WORDING": "The edit adds evaluative, loaded or certainty-changing wording "
    "the source does not use.",
    "REMOVED_CONTEXT": "The edit removes sourced context, attribution or a qualifier.",
    "CITATION_DATE": "A rendered citation date needs review against the edited source link.",
    "VALUE_CHANGED": "The edit changes a value the cited source does not state. Is this a correction?",
}

# The judge prompt asks it to mark quoted deleted text, e.g. "... (removed)".
_REMOVAL_MARK: Final = re.compile(r"\s*\((?:removed|deleted)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class SpanPolicy:
    """The display and routing decision for one independently classified span."""

    kind: FlagKind | None
    tier: FlagTier | None
    title: str | None


_SPAN_FLAG_KIND: Final[dict[str, FlagKind]] = {
    "CONTRADICTION": "FACT",
    "VALUE_CHANGE": "FACT",
    "REMOVED_QUALIFIER": "REMOVED_CONTEXT",
    "MOTIVE_CAUSE": "MOTIVE",
    "EVALUATIVE_LABEL": "FRAMING",
    "EDITORIAL_VOICE": "FRAMING",
    "NON_ENCYCLOPEDIC": "FRAMING",
}

_SPAN_TITLE: Final = {
    "CONTRADICTION": "Claim contradicts cited source",
    "VALUE_CHANGE": "Changed value needs source review",
    "REMOVED_QUALIFIER": "Sourced context was removed",
    "MOTIVE_CAUSE": "Unsupported motive or cause",
    "EVALUATIVE_LABEL": "Evaluative label needs review",
    "EDITORIAL_VOICE": "Editorial voice needs review",
    "NON_ENCYCLOPEDIC": "Non-encyclopedic content needs review",
    "SIZE_RANK_CLAIM": "Size or rank claim needs source review",
}


def _source_states_span(span: FlaggedSpan, window: SourceWindow | None) -> bool:
    if window is None:
        return False
    source = _norm(window.text)
    return bool(source) and _norm(span.exact_substring) in source


def span_policy(
    span: FlaggedSpan, judge_tier: FlagTier, window: SourceWindow | None
) -> SpanPolicy:
    """Apply the owner's wording policy without trusting a unit-level verdict."""
    span_type = span.span_type.value
    if span_type in {"INTENSIFIER", "REGISTER"}:
        return SpanPolicy(None, None, None)
    if span_type == "SIZE_RANK_CLAIM":
        if _source_states_span(span, window):
            return SpanPolicy(None, None, None)
        return SpanPolicy("FACT", "review", _SPAN_TITLE[span_type])
    if span_type == "REMOVED_QUALIFIER" and span.explanation.startswith(
        "Multiple cited sentences were removed"
    ):
        return SpanPolicy("REMOVED_CONTEXT", "review", _SPAN_TITLE[span_type])
    return SpanPolicy(_SPAN_FLAG_KIND[span_type], judge_tier, _SPAN_TITLE[span_type])


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def reason_code(output: AuditOutput, old_text: str, new_text: str) -> ReasonCode | None:
    """None for non-flag verdicts."""
    if output.verdict == "FLAG_G1_FACT":
        if any(
            span.explanation.startswith("VALUE_CHANGED:")
            for span in output.flagged_spans
        ):
            return "VALUE_CHANGED"
        return "CONTRADICTS_SOURCE"
    if output.verdict == "FLAG_G3_MOTIVE":
        return "UNSUPPORTED_CLAIM"
    if output.verdict != "FLAG_G2_FRAMING":
        return None
    old, new = _norm(old_text), _norm(new_text)
    spans = [
        _norm(_REMOVAL_MARK.sub("", s.exact_substring)) for s in output.flagged_spans
    ]
    removed = [s for s in spans if s and s in old and s not in new]
    if spans and 2 * len(removed) >= len(spans):
        return "REMOVED_CONTEXT"
    return "LOADED_WORDING"

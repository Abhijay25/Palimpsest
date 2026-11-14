"""Build UI flags from audit results without performing further audit work."""

import re
from dataclasses import dataclass

from palimpsest.citation_dates import CitationDateFinding
from palimpsest.reasons import ReasonCode
from palimpsest.schema import (
    AuditOutput,
    DisplayFlaggedSpan,
    Flag,
    FlagEvidence,
    FlagEvidenceSource,
    FlagKind,
    FlagSide,
    FlagTier,
    Verdict,
)
from palimpsest.stealth.models import HiddenFinding
from palimpsest.stealth.sanitizer import looks_like_instruction

_REMOVAL_MARK = re.compile(r"\s*\((?:removed|deleted)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class JudgeFlagInput:
    unit_index: int
    output: AuditOutput
    reason_code: ReasonCode | None
    tier: FlagTier
    old_text: str
    new_text: str
    old_wikitext: str
    new_wikitext: str
    citations: list[str]
    evidence: list[FlagEvidence]


@dataclass(frozen=True)
class StealthFlagInput:
    finding: HiddenFinding
    tier: FlagTier
    side_text: str
    evidence_source: FlagEvidenceSource
    evidence_url: str | None = None


def _offsets(text: str, anchor: str) -> tuple[int | None, int | None]:
    """Return an offset only when an anchor has one unambiguous raw location."""
    if not anchor or text.count(anchor) != 1:
        return None, None
    start = text.find(anchor)
    return start, start + len(anchor)


def _offsets_from_span(
    text: str, anchor: str, char_span: tuple[int, int]
) -> tuple[int | None, int | None]:
    start, end = char_span
    if 0 <= start <= end <= len(text) and text[start:end] == anchor:
        return start, end
    return _offsets(text, anchor)


def _judge_kind(reason: ReasonCode | None, verdict: Verdict) -> FlagKind:
    by_reason: dict[ReasonCode, FlagKind] = {
        "CONTRADICTS_SOURCE": "FACT",
        "LOADED_WORDING": "FRAMING",
        "UNSUPPORTED_CLAIM": "MOTIVE",
        "REMOVED_CONTEXT": "REMOVED_CONTEXT",
        "CITATION_DATE": "CITATION_DATE",
    }
    if reason is not None:
        return by_reason[reason]
    if verdict == Verdict.FLAG_G1_FACT:
        return "FACT"
    if verdict == Verdict.FLAG_G3_MOTIVE:
        return "MOTIVE"
    return "FRAMING"


def _judge_title(kind: FlagKind) -> str:
    return {
        "FACT": "Claim contradicts cited source",
        "FRAMING": "Loaded wording needs review",
        "MOTIVE": "Unsupported motive or claim",
        "REMOVED_CONTEXT": "Sourced context was removed",
        "HIDDEN_TEXT": "Hidden text detected",
        "CITATION_DATE": "Citation date needs review",
        "CITED_PAGE": "Cited page hidden text detected",
    }[kind]


def _context(text: str, anchor: str, fallback: str) -> str:
    return DisplayFlaggedSpan.context_for(text, anchor) or fallback


_TRAILING_YEAR = re.compile(r"[\s,]*\d{4}\s*$")


def _wikitext_anchor(wikitext: str, candidates: list[str]) -> str:
    """Pick the first candidate that occurs in the wikitext shown in the diff.

    Rendered values (dates with a template-added year, text on a cited page) often do
    not appear verbatim in the wikitext, so the UI could not highlight them.
    """
    for candidate in candidates:
        if candidate and candidate in wikitext:
            return candidate
    return next((candidate for candidate in candidates if candidate), "")


def _citation_title(code: str) -> str:
    if code == "FUTURE_DATE":
        return "Future citation date"
    return "Citation revision date mismatch"


def build_flags(
    judge_inputs: list[JudgeFlagInput],
    stealth_inputs: list[StealthFlagInput],
    citation_findings: list[CitationDateFinding],
    render_findings: list[HiddenFinding],
    new_wikitext: str,
    render_citations: list[str],
) -> list[Flag]:
    """Build the complete response flag list from already-computed audit data."""
    flags: list[Flag] = []
    for judge_input in judge_inputs:
        kind = _judge_kind(judge_input.reason_code, judge_input.output.verdict)
        removed = kind == "REMOVED_CONTEXT"
        side: FlagSide = "old" if removed else "new"
        side_text = judge_input.old_wikitext if removed else judge_input.new_wikitext
        context_text = judge_input.old_text if removed else judge_input.new_text
        for span_index, span in enumerate(judge_input.output.flagged_spans):
            anchor = (
                _REMOVAL_MARK.sub("", span.exact_substring)
                if removed
                else span.exact_substring
            )
            start, end = _offsets(side_text, anchor)
            flags.append(
                Flag(
                    id=f"u{judge_input.unit_index}-s{span_index}",
                    kind=kind,
                    tier=judge_input.tier,
                    title=_judge_title(kind),
                    reason=span.explanation,
                    confidence=judge_input.output.confidence,
                    side=side,
                    anchor_text=anchor,
                    anchor_start=start,
                    anchor_end=end,
                    context_sentence=_context(context_text, anchor, span.explanation),
                    evidence=judge_input.evidence,
                    citations=judge_input.citations,
                    neutral_rewrite=judge_input.output.neutral_rewrite,
                    check="judge",
                )
            )
    for index, stealth_input in enumerate(stealth_inputs):
        finding = stealth_input.finding
        anchor = _wikitext_anchor(
            stealth_input.side_text,
            [finding.raw_snippet, stealth_input.evidence_url or ""],
        )
        start, end = _offsets_from_span(
            stealth_input.side_text, anchor, finding.char_span
        )
        flags.append(
            Flag(
                id=f"h{index}",
                kind="HIDDEN_TEXT",
                tier=stealth_input.tier,
                title=_judge_title("HIDDEN_TEXT"),
                reason=finding.explanation,
                confidence=finding.confidence,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=_context(
                    stealth_input.side_text, anchor, finding.decoded_hidden_text
                ),
                evidence=[
                    FlagEvidence(
                        source=stealth_input.evidence_source,
                        quote=finding.decoded_hidden_text,
                        url=stealth_input.evidence_url,
                    )
                ],
                citations=(
                    [stealth_input.evidence_url] if stealth_input.evidence_url else []
                ),
                neutral_rewrite=None,
                check="stealth",
            )
        )
    for index, citation_finding in enumerate(citation_findings):
        anchor = _wikitext_anchor(
            new_wikitext,
            [
                citation_finding.rendered_date,
                _TRAILING_YEAR.sub("", citation_finding.rendered_date),
                citation_finding.url,
            ],
        )
        start, end = _offsets(new_wikitext, anchor)
        flags.append(
            Flag(
                id=f"c{index}",
                kind="CITATION_DATE",
                tier="review",
                title=_citation_title(citation_finding.code),
                reason=(
                    f"{citation_finding.code.replace('_', ' ').capitalize()}: "
                    f"{citation_finding.rendered_date}."
                ),
                confidence=1.0,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=citation_finding.snippet,
                evidence=[
                    FlagEvidence(
                        source="cited",
                        quote=citation_finding.snippet,
                        url=citation_finding.url,
                    )
                ],
                citations=[citation_finding.url],
                neutral_rewrite=None,
                check="citation_dates",
            )
        )
    escalating = [
        render_finding
        for render_finding in render_findings
        if looks_like_instruction(render_finding.decoded_hidden_text)
    ]
    for index, render_finding in enumerate(escalating):
        anchor = _wikitext_anchor(
            new_wikitext, [render_finding.raw_snippet, *render_citations]
        )
        start, end = _offsets(new_wikitext, anchor)
        flags.append(
            Flag(
                id=f"r{index}",
                kind="CITED_PAGE",
                tier="admin",
                title=_judge_title("CITED_PAGE"),
                reason=render_finding.explanation,
                confidence=render_finding.confidence,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=render_finding.decoded_hidden_text,
                evidence=[
                    FlagEvidence(
                        source="cited", quote=render_finding.decoded_hidden_text
                    )
                ],
                citations=render_citations,
                neutral_rewrite=None,
                check="render",
            )
        )
    return flags

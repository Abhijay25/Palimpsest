"""Build UI flags from audit results without performing further audit work."""

import re
from dataclasses import dataclass

from palimpsest import display_text
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
    SourceWindow,
    Verdict,
)
from palimpsest.stealth.models import HiddenFinding
from palimpsest.stealth.sanitizer import has_strong_instruction

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
    window: SourceWindow | None = None


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
        "VALUE_CHANGED": "FACT",
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


_TITLE_MAX = 80
_QUOTE_MAX = 320


def _titled(label: str, anchor: str) -> str:
    """Kind label plus the flagged words, e.g. 'Loaded wording: “a great American”'."""
    words = display_text.plain(anchor) or anchor
    room = _TITLE_MAX - len(label) - 4
    if not words or room < 8:
        return label[:_TITLE_MAX]
    short = words if len(words) <= room else words[: room - 1].rstrip() + "…"
    return f"{label}: “{short}”"


def _rewrite_sentence(
    rewrite: str | None, context_text: str, anchor: str
) -> str | None:
    """Only the rewritten sentence that replaces the flagged one, as plain text."""
    if not rewrite:
        return None
    flagged = display_text.sentence_with(context_text, anchor)
    return display_text.matching_sentence(rewrite, flagged) or display_text.shorten(
        display_text.plain(rewrite)
    )


def _before_after(
    judge_input: "JudgeFlagInput", anchor: str, removed: bool
) -> dict[str, str | None]:
    """The flagged sentence on its side and the closest sentence on the other side."""
    old_text, new_text = judge_input.old_text, judge_input.new_text
    if removed:
        before = display_text.sentence_with(old_text, anchor)
        return {
            "before": before,
            "after": display_text.matching_sentence(new_text, before),
        }
    after = display_text.sentence_with(new_text, anchor)
    return {"before": display_text.matching_sentence(old_text, after), "after": after}


def _readable(flag: Flag) -> Flag:
    """Plain, bounded evidence text; drop evidence items with nothing to show."""
    evidence = [
        item.model_copy(
            update={
                "quote": display_text.shorten(
                    display_text.plain(item.quote), _QUOTE_MAX
                )
            }
        )
        for item in flag.evidence
        if display_text.plain(item.quote)
    ]
    return flag.model_copy(update={"evidence": evidence})


def _citation_title(code: str) -> str:
    if code == "FUTURE_DATE":
        return "Future citation date"
    return "Citation revision date mismatch"


def _highlight_excerpts(text: str) -> list[str]:
    """Extract labeled Exa snippets without exposing their labels as evidence."""
    return [
        excerpt.strip()
        for excerpt in re.split(r"\[Highlight \d+\]\s*", text)
        if excerpt.strip()
    ]


def _judge_evidence(judge_input: JudgeFlagInput) -> list[FlagEvidence]:
    window = judge_input.window
    if window is None or window.method != "highlights":
        return judge_input.evidence
    excerpts = _highlight_excerpts(window.text)
    if not excerpts:
        return []
    cited = [
        proposition.evidence_quote_from_ref
        for proposition in judge_input.output.atomic_propositions
        if proposition.evidence_quote_from_ref
    ]
    selected = [
        excerpt
        for excerpt in excerpts
        if any(quote in excerpt or excerpt in quote for quote in cited)
    ]
    quotes = selected or [excerpts[0]]
    return [
        FlagEvidence(source="cited", quote=quote, url=window.url) for quote in quotes
    ]


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
        for span_index, span in enumerate(judge_input.output.flagged_spans):
            anchor = _REMOVAL_MARK.sub("", span.exact_substring)
            # The side is wherever the flagged words are: a deletion can be judged as a
            # fact or framing problem, not only as REMOVED_CONTEXT.
            removed = anchor not in judge_input.new_wikitext and (
                anchor in judge_input.old_wikitext or kind == "REMOVED_CONTEXT"
            )
            if not removed:
                anchor = span.exact_substring
            side: FlagSide = "old" if removed else "new"
            side_text = (
                judge_input.old_wikitext if removed else judge_input.new_wikitext
            )
            context_text = judge_input.old_text if removed else judge_input.new_text
            start, end = _offsets(side_text, anchor)
            flags.append(
                Flag(
                    id=f"u{judge_input.unit_index}-s{span_index}",
                    kind=kind,
                    tier=judge_input.tier,
                    title=_titled(_judge_title(kind), anchor),
                    reason=span.explanation,
                    confidence=judge_input.output.confidence,
                    side=side,
                    anchor_text=anchor,
                    anchor_start=start,
                    anchor_end=end,
                    context_sentence=display_text.sentence_with(
                        _context(context_text, anchor, span.explanation), anchor
                    ),
                    evidence=_judge_evidence(judge_input),
                    citations=judge_input.citations,
                    neutral_rewrite=_rewrite_sentence(
                        judge_input.output.neutral_rewrite, context_text, anchor
                    ),
                    check="judge",
                    **_before_after(judge_input, anchor, removed),
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
        if has_strong_instruction(render_finding.decoded_hidden_text)
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
    return [_readable(flag) for flag in flags]

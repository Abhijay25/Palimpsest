"""Build UI flags from audit results without performing further audit work."""

import os
import re
from dataclasses import dataclass, field

from palimpsest import display_text
from palimpsest.cherry_pick import CherryPickFinding
from palimpsest.citation_dates import CitationDateFinding
from palimpsest.citation_lifecycle import CitationDriftReport
from palimpsest.consistency import ConsistencyFinding, article_url
from palimpsest.reasons import ReasonCode, span_policy
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
    linked_evidence: list[FlagEvidence] = field(default_factory=list)
    changed_wikitext: str | None = None


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


def _containing_sentence_or_clause(text: str, span: str) -> str:
    """Return the complete changed sentence containing a judge-selected span."""
    start = text.find(span)
    if start < 0:
        return text.strip()
    sentence_start = 0
    for index in range(start - 1, -1, -1):
        if text[index] not in ".!?;":
            continue
        if index + 1 == len(text) or text[index + 1].isspace():
            sentence_start = index + 1
            break
    sentence_end = len(text)
    for index in range(start + len(span), len(text)):
        if text[index] not in ".!?;":
            continue
        if index + 1 == len(text) or text[index + 1].isspace():
            sentence_end = index + 1
            break
    return text[sentence_start:sentence_end].strip()


def _judge_anchor(judge_input: JudgeFlagInput, span: str) -> str:
    """Use the changed sentence, not the judge's variable substring, as an anchor."""
    changed = judge_input.changed_wikitext or judge_input.new_text
    return _containing_sentence_or_clause(changed, span)


def order_flags(flags: list[Flag]) -> list[Flag]:
    """Keep response order independent of detector and model completion order."""
    return sorted(
        flags,
        key=lambda flag: (
            flag.anchor_start is None,
            flag.anchor_start if flag.anchor_start is not None else 0,
            flag.kind,
            flag.id,
        ),
    )


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
        "CHERRY_PICK": "Citation omits source context",
        "OUT_OF_SYNC": "Out of sync with the page",
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


def _normalised_reason(reason: str) -> str:
    return " ".join(reason.casefold().split())


def _collapse(flags: list[Flag]) -> list[Flag]:
    """Merge repeated findings while keeping the first diff anchor."""
    collapsed: list[Flag] = []
    positions: dict[tuple[str, str, str, str], int] = {}
    for flag in flags:
        key = (flag.kind, flag.tier, flag.check, _normalised_reason(flag.reason))
        index = positions.get(key)
        if index is None:
            positions[key] = len(collapsed)
            collapsed.append(flag)
            continue
        first = collapsed[index]
        occurrences = first.occurrences + 1
        collapsed[index] = first.model_copy(
            update={
                "occurrences": occurrences,
                "reason": f"{re.sub(r' \(\d+ places\)$', '', first.reason)} ({occurrences} places)",
            }
        )
    return collapsed


_OUT_OF_SYNC_REASON = re.compile(r"^The edit changes .+? to (.+?), but the section '")


def suppress_out_of_sync_duplicates(flags: list[Flag]) -> list[Flag]:
    """Prefer a page contradiction over a duplicate judge fact finding."""
    out_of_sync = [flag for flag in flags if flag.kind == "OUT_OF_SYNC"]
    result: list[Flag] = []
    for flag in flags:
        if flag.kind != "FACT" or flag.check != "judge":
            result.append(flag)
            continue
        unit = re.match(r"^u(\d+)-", flag.id)
        if unit is None:
            result.append(flag)
            continue
        duplicate = False
        for page_flag in out_of_sync:
            page_unit = re.match(r"^o(\d+)-", page_flag.id)
            value = _OUT_OF_SYNC_REASON.match(page_flag.reason)
            # Paragraph numbering differs between the judge and the page check, so
            # the same anchor on the same side is enough to call it a duplicate.
            positioned = (
                flag.anchor_start is not None and page_flag.anchor_start is not None
            )
            if flag.side == page_flag.side and (
                flag.anchor_start == page_flag.anchor_start
                if positioned
                else flag.anchor_text.strip() == page_flag.anchor_text.strip()
            ):
                duplicate = True
                break
            if (
                page_unit is None
                or value is None
                or page_unit.group(1) != unit.group(1)
                or flag.side != page_flag.side
            ):
                continue
            overlaps = (
                flag.anchor_start is not None
                and flag.anchor_end is not None
                and page_flag.anchor_start is not None
                and page_flag.anchor_end is not None
                and flag.anchor_start < page_flag.anchor_end
                and page_flag.anchor_start < flag.anchor_end
            )
            same_sentence = _normalised_reason(
                flag.context_sentence
            ) == _normalised_reason(page_flag.context_sentence)
            if same_sentence and (
                overlaps or value.group(1).casefold() in flag.anchor_text.casefold()
            ):
                duplicate = True
                break
        if not duplicate:
            result.append(flag)
    return result


def _citation_title(code: str) -> str:
    if code == "FUTURE_DATE":
        return "Future citation date"
    return "Citation revision date mismatch"


_NOISY_DRIFT = frozenset({"SEMANTIC_RUGPULL", "DOMAIN_HIJACK_SUSPECTED"})


def citation_lifecycle_flags(
    findings: list[CitationDriftReport], new_wikitext: str
) -> list[Flag]:
    """Map archived-versus-live citation drift into the stable UI flag contract."""
    messages = {
        "HARD_LINK_ROT": "Cited page is no longer available",
        "SOFT_404_REDIRECT": "Cited page now redirects to an unrelated page",
        "DOMAIN_HIJACK_SUSPECTED": "Cited site changed hands since it was cited",
        "SEMANTIC_RUGPULL": "Cited page changed substantially since it was cited",
        "UNRESPONSIVE_SITE": "Cited site did not respond (it may be down)",
        "DELAYED_STEALTH_INJECTION": (
            "Cited page gained hidden text since it was cited"
        ),
    }
    flags: list[Flag] = []
    for index, finding in enumerate(findings):
        reason = messages.get(finding.drift_status)
        if reason is None:
            continue
        # Whole-page drift from the offline embedder flagged stable pages in live tests
        # (PLAN.md, A1); only hard signals reach the admin unless explicitly enabled.
        if (
            finding.drift_status in _NOISY_DRIFT
            and os.environ.get("PALIMPSEST_A1_DRIFT") != "1"
        ):
            continue
        anchor = _wikitext_anchor(new_wikitext, [finding.url])
        start, end = _offsets(new_wikitext, anchor)
        flags.append(
            Flag(
                id=f"l{index}",
                kind="CITED_PAGE",
                tier=(
                    "admin"
                    if finding.drift_status == "DELAYED_STEALTH_INJECTION"
                    else "review"
                ),
                title=reason,
                reason=reason,
                confidence=1.0,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=reason,
                evidence=[
                    FlagEvidence(
                        source="cited",
                        quote=(
                            f"Baseline: {finding.baseline_excerpt}\n"
                            f"Live: {finding.live_excerpt}"
                        ),
                        url=finding.wayback_fallback_url,
                    )
                ],
                citations=[finding.url],
                neutral_rewrite=None,
                check="citation_lifecycle",
            )
        )
    return flags


def cherry_pick_flags(
    findings: list[CherryPickFinding], new_wikitext: str
) -> list[Flag]:
    """Map B2 findings into the same stable flag record as the other checks."""
    flags: list[Flag] = []
    for index, finding in enumerate(findings):
        anchor = finding.claim if finding.claim in new_wikitext else ""
        start, end = _offsets(new_wikitext, anchor)
        reason = f"The edit says “{finding.claim}”; the cited source says “{finding.source_passage}”."
        flags.append(
            Flag(
                id=f"b{index}",
                kind="CHERRY_PICK",
                tier=finding.tier,
                title=_titled(_judge_title("CHERRY_PICK"), anchor),
                reason=reason,
                confidence=finding.confidence,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=_context(new_wikitext, anchor, finding.claim),
                evidence=[
                    FlagEvidence(
                        source="cited",
                        quote=finding.source_passage,
                        url=finding.citations[0] if finding.citations else None,
                    )
                ],
                citations=finding.citations,
                neutral_rewrite=finding.balanced_rewrite,
                check="cherry_pick",
            )
        )
    return flags


def consistency_flags(
    findings: list[ConsistencyFinding], lang: str, title: str, new_wikitext: str
) -> list[Flag]:
    """Map page-internal contradictions into stable, directly jumpable UI flags."""
    flags: list[Flag] = []
    for index, finding in enumerate(findings):
        anchor = _wikitext_anchor(
            new_wikitext, [finding.new_value, finding.changed_sentence]
        )
        start, end = _offsets(new_wikitext, anchor)
        flags.append(
            Flag(
                id=f"o{finding.unit_index}-{index}",
                kind="OUT_OF_SYNC",
                tier="admin" if finding.method == "deterministic" else "review",
                title=(
                    f"Out of sync with the page: "
                    f"{finding.new_value} vs {finding.old_value}"
                )[:_TITLE_MAX],
                reason=(
                    f"The edit changes {finding.old_value} to {finding.new_value}, but "
                    f"the section '{finding.section}' still says {finding.old_value}."
                ),
                confidence=1.0 if finding.method == "deterministic" else 0.7,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=end,
                context_sentence=finding.changed_sentence,
                evidence=[
                    FlagEvidence(
                        source="page",
                        quote=finding.quote,
                        section=finding.section,
                        url=article_url(lang, title, finding.section),
                    )
                ],
                citations=[],
                neutral_rewrite=None,
                check="consistency",
                related_anchor_text=finding.quote if finding.quote_in_diff else None,
            )
        )
    return flags


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
        return [*judge_input.evidence, *judge_input.linked_evidence]
    excerpts = _highlight_excerpts(window.text)
    if not excerpts:
        return list(judge_input.linked_evidence)
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
    evidence = [
        FlagEvidence(source="cited", quote=quote, url=window.url) for quote in quotes
    ]
    if window.whole_source_checked:
        evidence.append(
            FlagEvidence(
                source="cited",
                quote=(
                    window.whole_source_passages[0]
                    if window.whole_source_passages
                    else "Checked the whole cited source; no supporting passage found."
                ),
                url=window.url,
            )
        )
    return [*evidence, *judge_input.linked_evidence]


def build_flags(
    judge_inputs: list[JudgeFlagInput],
    stealth_inputs: list[StealthFlagInput],
    citation_findings: list[CitationDateFinding],
    render_findings: list[HiddenFinding],
    new_wikitext: str,
    render_citations: list[str],
    citation_lifecycle_findings: list[CitationDriftReport] | None = None,
) -> list[Flag]:
    """Build the complete response flag list from already-computed audit data."""
    flags: list[Flag] = []
    for judge_input in judge_inputs:
        for span_index, span in enumerate(judge_input.output.flagged_spans):
            policy = span_policy(span, judge_input.tier, judge_input.window)
            if policy.kind is None or policy.tier is None or policy.title is None:
                continue
            kind = policy.kind
            anchor = _REMOVAL_MARK.sub("", span.exact_substring)
            # The side is wherever the flagged words are: a deletion can be judged as a
            # fact or framing problem, not only as REMOVED_CONTEXT.
            removed = anchor not in judge_input.new_wikitext and (
                anchor in judge_input.old_wikitext or kind == "REMOVED_CONTEXT"
            )
            if not removed:
                anchor = _judge_anchor(judge_input, span.exact_substring)
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
                    tier=policy.tier,
                    title=_titled(policy.title, anchor),
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
    for index, render_finding in enumerate(render_findings):
        anchor = _wikitext_anchor(
            new_wikitext, [render_finding.raw_snippet, *render_citations]
        )
        start, end = _offsets(new_wikitext, anchor)
        flags.append(
            Flag(
                id=f"r{index}",
                kind="CITED_PAGE",
                tier=(
                    "admin"
                    if has_strong_instruction(render_finding.decoded_hidden_text)
                    else "review"
                ),
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
    flags.extend(
        citation_lifecycle_flags(citation_lifecycle_findings or [], new_wikitext)
    )
    return order_flags(_collapse([_readable(flag) for flag in flags]))

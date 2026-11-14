import re
import time
import uuid
from collections.abc import Iterable
from typing import Literal

from palimpsest.stealth.models import (
    HiddenFinding,
    ScanResult,
    StealthStatus,
    VectorType,
)
from palimpsest.stealth.sanitizer import (
    INVISIBLE_CHARS,
    decode_unicode_tags,
    detect_homoglyphs,
    extract_hidden_channels,
    looks_like_instruction,
    remove_spans,
    scan_invisible_controls,
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n")
# Scripts that never need joiners: an invisible character between two of their
# letters splits a word to dodge keyword filters (language-neutral signal).
_NO_JOINER_LETTER = "A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff"
_INTRA_WORD_INVISIBLE = re.compile(
    f"(?<=[{_NO_JOINER_LETTER}])[\u200b-\u200d\u2060\ufeff]+(?=[{_NO_JOINER_LETTER}])"
)
_WORD = re.compile(r"\w+")
_MARKUP_TAG = re.compile(r"<[^>]*>")
# One stray zero-width space is a common copy-paste or line-break hint in long
# compounds; an attacker splits several words.
SPLIT_WORD_MIN = 2
VISIBLE_SCREEN_MIN_WORDS = 4
VISIBLE_SCREEN_MAX_CHARS = 2000
SCREEN_CLASSIFICATION = "SCREEN_FOR_INJECTION"
_INVISIBLE_TABLE = {ord(c): None for c in INVISIBLE_CHARS}

_TRIAGE_FIRST_VECTORS = frozenset(
    {
        VectorType.TEMPLATE_PARAM_TEXT,
        VectorType.A11Y_ALT_POISONING,
        VectorType.ATTRIBUTE_TEXT,
    }
)

TargetType = Literal["WIKIPEDIA_DIFF", "EXTERNAL_REF_PAGE"]

# Higher rank wins: CRITICAL > CSS > HOMOGLYPH > BENIGN > CLEAN.
_RANK: dict[StealthStatus, int] = {
    StealthStatus.CLEAN: 0,
    StealthStatus.BENIGN_NOTES_ONLY: 1,
    StealthStatus.HOMOGLYPH_SPOOFING: 2,
    StealthStatus.CSS_CLOAKING_DETECTED: 3,
    StealthStatus.CRITICAL_AI_POISONING: 4,
}


def worst_status(statuses: Iterable[StealthStatus]) -> StealthStatus:
    return max(statuses, key=_RANK.__getitem__, default=StealthStatus.CLEAN)


def reportable_findings(result: ScanResult) -> list[HiddenFinding]:
    """Findings to report to API/pipeline callers.

    A clean or notes-only scan cannot create a hidden-text flag. Provisional
    channels require an escalation; an unavailable triage may still leave a
    cloaked (non-comment) channel for review.
    """
    if result.stealth_status in {
        StealthStatus.CLEAN,
        StealthStatus.BENIGN_NOTES_ONLY,
    }:
        return []
    return [
        f
        for f in result.hidden_findings
        if f.classification
        not in {
            SCREEN_CLASSIFICATION,
            "BENIGN_EDITOR_NOTE_PROVISIONAL",
            "BENIGN_EDITOR_NOTE",
            "NEEDS_TRIAGE",
            "TRIAGE_NO_FLAG",
        }
        and not (
            f.classification == "TRIAGE_MISSING"
            and f.vector_type == VectorType.HTML_COMMENT
        )
    ]


def _screen_chunks(
    pieces: list[tuple[str, tuple[int, int] | None]],
) -> list[tuple[str, list[tuple[int, int]]]]:
    """Group screened sentences into chunks of at most VISIBLE_SCREEN_MAX_CHARS.

    Splits on sentence boundaries; one sentence longer than the limit is cut
    into limit-sized slices so that no added text goes unscreened.
    """
    chunks: list[tuple[str, list[tuple[int, int]]]] = []
    current = ""
    spans: list[tuple[int, int]] = []

    def flush() -> None:
        nonlocal current, spans
        if current:
            chunks.append((current, spans))
        current, spans = "", []

    for prose, span in pieces:
        for offset in range(0, len(prose), VISIBLE_SCREEN_MAX_CHARS):
            part = prose[offset : offset + VISIBLE_SCREEN_MAX_CHARS]
            if current and len(current) + 1 + len(part) > VISIBLE_SCREEN_MAX_CHARS:
                flush()
            current = f"{current} {part}" if current else part
            if span is not None:
                spans.append(span)
    flush()
    return chunks


def scan(text: str, target_type: TargetType, old_text: str | None = None) -> ScanResult:
    started = time.perf_counter()

    def is_new(snippet: str) -> bool:
        return old_text is None or snippet not in old_text

    findings: list[HiddenFinding] = []
    status = StealthStatus.CLEAN

    def add(finding: HiddenFinding, contributes: StealthStatus | None) -> None:
        nonlocal status
        findings.append(finding)
        if contributes is not None and _RANK[contributes] > _RANK[status]:
            status = contributes

    tags = decode_unicode_tags(text)
    for payload in tags.payloads:
        raw = text[payload.span[0] : payload.span[1]]
        if not is_new(raw):
            continue
        add(
            HiddenFinding(
                vector_type=VectorType.UNICODE_TAG_SMUGGLING,
                raw_snippet=raw,
                decoded_hidden_text=payload.decoded,
                char_span=payload.span,
                classification="FLAG_STEALTH_PROMPT_INJECTION",
                confidence=0.99,
                explanation="Unicode Tag characters (U+E0000-U+E007F) encode hidden ASCII "
                "text that LLM tokenizers read but humans cannot see.",
            ),
            StealthStatus.CRITICAL_AI_POISONING,
        )

    controls = scan_invisible_controls(text)
    intra_word_runs = {match.span() for match in _INTRA_WORD_INVISIBLE.finditer(text)}
    for run in controls.runs:
        raw = text[run.span[0] : run.span[1]]
        if not is_new(raw):
            continue
        intra_word = run.span in intra_word_runs
        add(
            HiddenFinding(
                vector_type=VectorType.INVISIBLE_CONTROL_CHARS,
                raw_snippet=raw,
                decoded_hidden_text="",
                char_span=run.span,
                classification="FLAG_BIDI_OVERRIDE"
                if run.is_bidi
                else "FLAG_CSS_CLOAKING"
                if intra_word
                else "INFO_ZERO_WIDTH",
                confidence=0.8 if run.is_bidi else 0.4,
                explanation="Bidirectional override control characters present."
                if run.is_bidi
                else "Invisible characters split a visible word."
                if intra_word
                else "Zero-width characters present; stripped from human text.",
            ),
            StealthStatus.HOMOGLYPH_SPOOFING
            if run.is_bidi
            else StealthStatus.CSS_CLOAKING_DETECTED
            if intra_word
            else None,
        )

    for homoglyph in detect_homoglyphs(text):
        if not is_new(homoglyph.token):
            continue
        add(
            HiddenFinding(
                vector_type=VectorType.HOMOGLYPH_MIXED_SCRIPT,
                raw_snippet=homoglyph.token,
                decoded_hidden_text="",
                char_span=homoglyph.span,
                classification="FLAG_HOMOGLYPH_SPOOFING",
                confidence=0.9,
                explanation="Single word mixes scripts: "
                + "+".join(homoglyph.scripts)
                + ".",
            ),
            StealthStatus.HOMOGLYPH_SPOOFING,
        )

    channels = extract_hidden_channels(text)
    if channels.unscanned_span is not None:
        span_start, span_end = channels.unscanned_span
        add(
            HiddenFinding(
                vector_type=VectorType.SCAN_TRUNCATED,
                raw_snippet=text[span_start : min(span_end, span_start + 200)],
                decoded_hidden_text="",
                char_span=channels.unscanned_span,
                classification="NEEDS_TRIAGE",
                confidence=0.5,
                explanation="Template parameter scan stopped at the size/nesting "
                "limit; remaining content was not inspected.",
            ),
            StealthStatus.BENIGN_NOTES_ONLY,
        )
    for item in channels.quarantined_items:
        if not is_new(item.raw_snippet):
            continue
        if item.vector_type in _TRIAGE_FIRST_VECTORS and not item.instruction_like:
            classification = "NEEDS_TRIAGE"
            contributes = StealthStatus.BENIGN_NOTES_ONLY
            confidence = 0.6
            explanation = "Template parameter or attribute text that may not render; pending triage."
        elif item.instruction_like:
            classification = "FLAG_STEALTH_PROMPT_INJECTION"
            contributes = StealthStatus.CRITICAL_AI_POISONING
            confidence = 0.95
            explanation = "Hidden channel contains instruction-like phrasing aimed at an AI reader."
        elif item.vector_type == VectorType.HTML_COMMENT:
            classification = "BENIGN_EDITOR_NOTE_PROVISIONAL"
            contributes = StealthStatus.BENIGN_NOTES_ONLY
            confidence = 0.5
            explanation = "Hidden comment without instruction phrasing; provisional pending triage."
        else:
            classification = "FLAG_CSS_CLOAKING"
            contributes = StealthStatus.CSS_CLOAKING_DETECTED
            confidence = 0.85
            explanation = "Text hidden from human readers but present for scrapers."
        add(
            HiddenFinding(
                vector_type=item.vector_type,
                raw_snippet=item.raw_snippet,
                decoded_hidden_text=item.hidden_text,
                char_span=item.span,
                classification=classification,
                confidence=confidence,
                explanation=explanation,
            ),
            contributes,
        )

    visible = remove_spans(
        text,
        [p.span for p in tags.payloads] + [i.span for i in channels.quarantined_items],
    )
    old_stripped = old_text.translate(_INVISIBLE_TABLE) if old_text else None
    screen_pieces: list[tuple[str, tuple[int, int] | None]] = []
    for sentence in _SENTENCE_BREAK.split(visible):
        clean = sentence.translate(_INVISIBLE_TABLE)
        if old_stripped is not None and clean in old_stripped:
            continue
        instruction_hint = looks_like_instruction(clean)
        split_word = len(_INTRA_WORD_INVISIBLE.findall(sentence)) >= SPLIT_WORD_MIN
        if not instruction_hint and not split_word:
            prose = _MARKUP_TAG.sub(" ", clean).strip()
            if (
                target_type == "WIKIPEDIA_DIFF"
                and old_text is not None
                and len(_WORD.findall(prose)) >= VISIBLE_SCREEN_MIN_WORDS
            ):
                first = text.find(sentence)
                screen_pieces.append(
                    (prose, (first, first + len(sentence)) if first >= 0 else None)
                )
            continue
        start = max(text.find(sentence), 0)
        span = (start, start + len(sentence))
        if clean != sentence:
            add(
                HiddenFinding(
                    vector_type=VectorType.INVISIBLE_CONTROL_CHARS,
                    raw_snippet=sentence,
                    decoded_hidden_text=clean,
                    char_span=span,
                    classification="FLAG_STEALTH_PROMPT_INJECTION"
                    if instruction_hint
                    else "NEEDS_TRIAGE",
                    confidence=0.95 if instruction_hint else 0.6,
                    explanation="Invisible characters split "
                    + ("an instruction" if instruction_hint else "words")
                    + " inside visible text; de-obfuscated sentence shown.",
                ),
                StealthStatus.CRITICAL_AI_POISONING
                if instruction_hint
                else StealthStatus.BENIGN_NOTES_ONLY,
            )
        elif not instruction_hint:
            continue
        else:
            add(
                HiddenFinding(
                    vector_type=VectorType.VISIBLE_INSTRUCTION,
                    raw_snippet=sentence,
                    decoded_hidden_text=clean,
                    char_span=span,
                    classification="NEEDS_TRIAGE",
                    confidence=0.3,
                    explanation="Visible added text contains instruction-like "
                    "phrasing; pending triage.",
                ),
                StealthStatus.BENIGN_NOTES_ONLY,
            )

    for item in channels.screen_items:
        if is_new(item.raw_snippet):
            add(
                HiddenFinding(
                    vector_type=item.vector_type,
                    raw_snippet=item.raw_snippet,
                    decoded_hidden_text=item.hidden_text,
                    char_span=item.span,
                    classification=SCREEN_CLASSIFICATION,
                    confidence=0.2,
                    explanation="Prose template parameter that may not render; "
                    "screened for instructions.",
                ),
                None,
            )
    for joined, chunk_spans in _screen_chunks(screen_pieces):
        add(
            HiddenFinding(
                vector_type=VectorType.VISIBLE_INSTRUCTION,
                raw_snippet=joined,
                decoded_hidden_text=joined,
                char_span=(
                    min((sp[0] for sp in chunk_spans), default=0),
                    max((sp[1] for sp in chunk_spans), default=0),
                ),
                classification=SCREEN_CLASSIFICATION,
                confidence=0.1,
                explanation="Added visible prose screened for instructions "
                "aimed at AI readers.",
            ),
            None,
        )

    removals = [p.span for p in tags.payloads] + [r.span for r in controls.runs]
    removals.extend(i.span for i in channels.quarantined_items)
    sanitized = remove_spans(text, removals)
    findings.sort(key=lambda f: f.char_span)
    return ScanResult(
        scan_id=f"stealth_{uuid.uuid4().hex[:8]}",
        target_type=target_type,
        stealth_status=status,
        scan_latency_ms=(time.perf_counter() - started) * 1000,
        sanitized_human_text=sanitized,
        hidden_findings=findings,
        removed_spans=removals,
    )

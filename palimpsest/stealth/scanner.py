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
    for run in controls.runs:
        raw = text[run.span[0] : run.span[1]]
        if not is_new(raw):
            continue
        add(
            HiddenFinding(
                vector_type=VectorType.INVISIBLE_CONTROL_CHARS,
                raw_snippet=raw,
                decoded_hidden_text="",
                char_span=run.span,
                classification="FLAG_BIDI_OVERRIDE"
                if run.is_bidi
                else "INFO_ZERO_WIDTH",
                confidence=0.8 if run.is_bidi else 0.4,
                explanation="Bidirectional override control characters present."
                if run.is_bidi
                else "Zero-width characters present; stripped from human text.",
            ),
            StealthStatus.HOMOGLYPH_SPOOFING if run.is_bidi else None,
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
    for item in channels.quarantined_items:
        if not is_new(item.raw_snippet):
            continue
        if item.vector_type in _TRIAGE_FIRST_VECTORS:
            classification = "NEEDS_TRIAGE"
            contributes = (
                StealthStatus.CRITICAL_AI_POISONING
                if item.instruction_like
                else StealthStatus.BENIGN_NOTES_ONLY
            )
            confidence = 0.6
            explanation = (
                "Template parameter or attribute text that may not render"
                + ("; instruction-like phrasing" if item.instruction_like else "")
                + "; pending triage."
            )
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
    for sentence in _SENTENCE_BREAK.split(visible):
        clean = sentence.translate(_INVISIBLE_TABLE)
        if not looks_like_instruction(clean):
            continue
        if old_stripped is not None and clean in old_stripped:
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
                    classification="FLAG_STEALTH_PROMPT_INJECTION",
                    confidence=0.95,
                    explanation="Invisible characters split an instruction inside "
                    "visible text; de-obfuscated sentence shown.",
                ),
                StealthStatus.CRITICAL_AI_POISONING,
            )
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

import re

from palimpsest.stealth.models import HiddenFinding, VectorType
from palimpsest.stealth.render import HiddenReason, RenderAudit
from palimpsest.stealth.sanitizer import looks_like_instruction
from palimpsest.stealth.scanner import scan

MIN_NODE_TOKENS = 4
FED_TO_JUDGE_RATIO = 0.6
MIN_SENTENCE_TOKENS = 6
SCRAPER_ONLY_CONTAINMENT = 0.5
# A judged sentence must be (mostly) in the rendered DOM to count as hidden;
# otherwise the page changed between fetches, or is a PDF/paywall (drift, r-p01).
IN_DOM_CONTAINMENT = 0.8

_TOKEN = re.compile(r"\w+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_REASON_VECTOR: dict[HiddenReason, VectorType] = {
    "occluded": VectorType.PIXEL_DOM_MISMATCH,
    "display_none": VectorType.CSS_HIDDEN_ELEMENT,
    "visibility_hidden": VectorType.CSS_HIDDEN_ELEMENT,
    "clipped": VectorType.CSS_HIDDEN_ELEMENT,
    "zero_size": VectorType.CSS_HIDDEN_ELEMENT,
    "offscreen": VectorType.CSS_HIDDEN_ELEMENT,
    "transparent": VectorType.CSS_ZERO_FONT,
    "low_contrast": VectorType.CSS_ZERO_FONT,
    "tiny_font": VectorType.CSS_ZERO_FONT,
}


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _normalized(text: str) -> str:
    return " ".join(_tokens(text))


def _containment(tokens: list[str], pool: set[str]) -> float:
    return sum(t in pool for t in tokens) / len(tokens) if tokens else 0.0


def judged_drift(audit: RenderAudit, judged_text: str) -> float:
    """Share of judged sentences absent from the rendered DOM (page drift or cloaking by client)."""
    dom_tokens = set(_tokens(audit.scraper_text))
    sentences = [
        t
        for t in (_tokens(s) for s in _SENTENCE_SPLIT.split(judged_text))
        if len(t) >= MIN_SENTENCE_TOKENS
    ]
    if not sentences:
        return 0.0
    absent = sum(_containment(t, dom_tokens) < IN_DOM_CONTAINMENT for t in sentences)
    return absent / len(sentences)


def fetched_html_findings(html: str) -> list[HiddenFinding]:
    """Detect hidden channels retained only in a cited page's fetched HTML.

    The same scanner used for edit wikitext sees comments, scripts, hidden
    elements, invisible controls, and accessibility-hidden text. Cited pages
    commonly include hidden navigation and consent UI, so only instruction-like
    hidden channels are findings.
    """
    return [
        finding
        for finding in scan(html, "EXTERNAL_REF_PAGE").hidden_findings
        if finding.classification == "FLAG_STEALTH_PROMPT_INJECTION"
    ]


def _deduplicate(findings: list[HiddenFinding]) -> list[HiddenFinding]:
    """Keep one finding when HTML and layout inspection observe the same text."""
    seen: set[str] = set()
    deduplicated: list[HiddenFinding] = []
    for finding in findings:
        key = _normalized(finding.decoded_hidden_text or finding.raw_snippet)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(finding)
    return deduplicated


def render_findings(audit: RenderAudit, judged_text: str | None) -> list[HiddenFinding]:
    findings = fetched_html_findings(audit.fetched_html) if audit.fetched_html else []
    judged_tokens = set(_tokens(judged_text)) if judged_text is not None else None
    visible_normalized = _normalized(audit.human_text)

    for node in audit.hidden_nodes:
        tokens = _tokens(node.text)
        if len(tokens) < MIN_NODE_TOKENS:
            continue
        if not looks_like_instruction(node.text):
            continue
        # Responsive duplicates (mobile menu, repeated headline) are also visible.
        if " ".join(tokens) in visible_normalized:
            continue
        fed = False
        if judged_tokens is not None:
            fed = (
                sum(t in judged_tokens for t in tokens) / len(tokens)
                >= FED_TO_JUDGE_RATIO
            )
            if not fed and not looks_like_instruction(node.text):
                continue
        seen = (
            "unknown (no judged text supplied)"
            if judged_tokens is None
            else (
                "the judge would have seen it"
                if fed
                else "the judge would not have seen it"
            )
        )
        findings.append(
            HiddenFinding(
                vector_type=_REASON_VECTOR[node.reason],
                raw_snippet=node.text[:300],
                decoded_hidden_text=node.text,
                char_span=(0, 0),
                classification="FLAG_STEALTH_PROMPT_INJECTION",
                confidence=0.95,
                explanation=f"Text hidden from humans ({node.reason}); {seen}.",
            )
        )

    if judged_text is not None:
        human_tokens = set(_tokens(audit.human_text))
        dom_tokens = set(_tokens(audit.scraper_text))
        for sentence in _SENTENCE_SPLIT.split(judged_text):
            tokens = _tokens(sentence)
            if len(tokens) < MIN_SENTENCE_TOKENS:
                continue
            if not looks_like_instruction(sentence):
                continue
            # Containment bounds Jaccard from above, so containment < 0.5 implies Jaccard < 0.5.
            contained = _containment(tokens, human_tokens)
            in_dom = _containment(tokens, dom_tokens) >= IN_DOM_CONTAINMENT
            if in_dom and contained < SCRAPER_ONLY_CONTAINMENT:
                findings.append(
                    HiddenFinding(
                        vector_type=VectorType.PIXEL_DOM_MISMATCH,
                        raw_snippet=sentence.strip()[:300],
                        decoded_hidden_text=sentence.strip(),
                        char_span=(0, 0),
                        classification="FLAG_STEALTH_PROMPT_INJECTION",
                        confidence=0.95,
                        explanation="Text given to the judge is not visible on the rendered page",
                    )
                )
    return _deduplicate(findings)

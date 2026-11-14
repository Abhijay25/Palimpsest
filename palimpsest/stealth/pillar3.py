import re

from palimpsest.stealth.models import HiddenFinding, VectorType
from palimpsest.stealth.render import HiddenReason, RenderAudit
from palimpsest.stealth.sanitizer import looks_like_instruction

MIN_NODE_TOKENS = 4
FED_TO_JUDGE_RATIO = 0.6
MIN_SENTENCE_TOKENS = 6
SCRAPER_ONLY_CONTAINMENT = 0.5

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


def render_findings(audit: RenderAudit, judged_text: str | None) -> list[HiddenFinding]:
    findings: list[HiddenFinding] = []
    judged_tokens = set(_tokens(judged_text)) if judged_text is not None else None

    for node in audit.hidden_nodes:
        tokens = _tokens(node.text)
        if len(tokens) < MIN_NODE_TOKENS:
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
                classification="NEEDS_TRIAGE",
                confidence=0.6,
                explanation=f"Text hidden from humans ({node.reason}); {seen}.",
            )
        )

    if judged_text is not None:
        human_tokens = set(_tokens(audit.human_text))
        for sentence in _SENTENCE_SPLIT.split(judged_text):
            tokens = _tokens(sentence)
            if len(tokens) < MIN_SENTENCE_TOKENS:
                continue
            # Containment bounds Jaccard from above, so containment < 0.5 implies Jaccard < 0.5.
            contained = sum(t in human_tokens for t in tokens) / len(tokens)
            if contained < SCRAPER_ONLY_CONTAINMENT:
                findings.append(
                    HiddenFinding(
                        vector_type=VectorType.PIXEL_DOM_MISMATCH,
                        raw_snippet=sentence.strip()[:300],
                        decoded_hidden_text=sentence.strip(),
                        char_span=(0, 0),
                        classification="NEEDS_TRIAGE",
                        confidence=0.5,
                        explanation="Text given to the judge is not visible on the rendered page",
                    )
                )
    return findings

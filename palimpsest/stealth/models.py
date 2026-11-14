from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class StealthStatus(StrEnum):
    CLEAN = "CLEAN"
    BENIGN_NOTES_ONLY = "BENIGN_NOTES_ONLY"
    CRITICAL_AI_POISONING = "CRITICAL_AI_POISONING"
    CSS_CLOAKING_DETECTED = "CSS_CLOAKING_DETECTED"
    HOMOGLYPH_SPOOFING = "HOMOGLYPH_SPOOFING"


class VectorType(StrEnum):
    UNICODE_TAG_SMUGGLING = "UNICODE_TAG_SMUGGLING"
    HTML_COMMENT = "HTML_COMMENT"
    CSS_ZERO_FONT = "CSS_ZERO_FONT"
    CSS_DISPLAY_NONE = "CSS_DISPLAY_NONE"
    A11Y_ALT_POISONING = "A11Y_ALT_POISONING"
    HOMOGLYPH_MIXED_SCRIPT = "HOMOGLYPH_MIXED_SCRIPT"
    PIXEL_DOM_MISMATCH = "PIXEL_DOM_MISMATCH"
    INVISIBLE_CONTROL_CHARS = "INVISIBLE_CONTROL_CHARS"
    CSS_HIDDEN_ELEMENT = "CSS_HIDDEN_ELEMENT"
    COLLAPSED_BLOCK = "COLLAPSED_BLOCK"
    TEMPLATE_PARAM_TEXT = "TEMPLATE_PARAM_TEXT"
    VISIBLE_INSTRUCTION = "VISIBLE_INSTRUCTION"
    ATTRIBUTE_TEXT = "ATTRIBUTE_TEXT"


class HiddenFinding(BaseModel):
    vector_type: VectorType
    raw_snippet: str
    decoded_hidden_text: str
    char_span: tuple[int, int]
    classification: str
    confidence: float
    explanation: str


class ScanResult(BaseModel):
    scan_id: str
    target_type: Literal["WIKIPEDIA_DIFF", "EXTERNAL_REF_PAGE"]
    stealth_status: StealthStatus
    scan_latency_ms: float
    sanitized_human_text: str
    hidden_findings: list[HiddenFinding]
    removed_spans: list[tuple[int, int]] = Field(default_factory=list, exclude=True)

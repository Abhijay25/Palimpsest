"""Audit output schema (spec section 10, fixed contract) and pipeline records."""

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field

LANG_CODE_PATTERN = r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$"
LangCode = Annotated[str, Field(pattern=LANG_CODE_PATTERN)]


class Verdict(StrEnum):
    CLEAN_PASS = "CLEAN_PASS"
    FLAG_G1_FACT = "FLAG_G1_FACT"
    FLAG_G2_FRAMING = "FLAG_G2_FRAMING"
    FLAG_G3_MOTIVE = "FLAG_G3_MOTIVE"
    EXPAND_CONTEXT = "EXPAND_CONTEXT"


class ClauseType(StrEnum):
    ACTION_FACT = "ACTION_FACT"
    MOTIVE_CAUSE = "MOTIVE_CAUSE"
    FRAMING_MODALITY = "FRAMING_MODALITY"


class Entailment(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED_EXTRAPOLATION = "UNSUPPORTED_EXTRAPOLATION"
    AMBIGUOUS_CONTEXT = "AMBIGUOUS_CONTEXT"


class Guideline(StrEnum):
    G1_FACT = "G1_FACT"
    G2_FRAMING = "G2_FRAMING"
    G3_MOTIVE = "G3_MOTIVE"


class ExpandDirection(StrEnum):
    NONE = "NONE"
    PREV = "PREV"
    NEXT = "NEXT"
    BOTH = "BOTH"


class AtomicProposition(BaseModel):
    clause_text: str
    clause_type: ClauseType
    source_entailment: Entailment
    evidence_quote_from_ref: str | None


class FlaggedSpan(BaseModel):
    exact_substring: str
    guideline_violated: Guideline
    explanation: str


class DisplayFlaggedSpan(FlaggedSpan):
    """A display wrapper that adds local context without changing judge output."""

    context_sentence: str | None = None

    _SENTENCE_TERMINATORS: ClassVar[frozenset[str]] = frozenset(
        ".!?\u3002\uff0e\uff01\uff1f\u061f"
    )
    _CONTEXT_LIMIT: ClassVar[int] = 400

    @classmethod
    def context_for(cls, judged_text: str, exact_substring: str) -> str | None:
        """Return the sentence containing a displayed span, bounded for responses."""
        if not exact_substring:
            return None
        match_start = judged_text.find(exact_substring)
        if match_start < 0:
            return None
        sentence_start = 0
        for index, character in enumerate(judged_text):
            if not cls._is_sentence_boundary(judged_text, index, character):
                continue
            sentence_end = index + 1
            if match_start < sentence_end:
                return cls._trim_context(
                    judged_text[sentence_start:sentence_end],
                    match_start - sentence_start,
                    len(exact_substring),
                )
            sentence_start = sentence_end
        return cls._trim_context(
            judged_text[sentence_start:],
            match_start - sentence_start,
            len(exact_substring),
        )

    @classmethod
    def _is_sentence_boundary(cls, text: str, index: int, character: str) -> bool:
        if character not in cls._SENTENCE_TERMINATORS:
            return False
        if index + 1 < len(text) and not text[index + 1].isspace():
            return False
        if character != ".":
            return True
        if cls._single_letter_abbreviation(text, index):
            return False
        return not cls._number_continues_after_period(text, index)

    @staticmethod
    def _single_letter_abbreviation(text: str, index: int) -> bool:
        if index == 0 or not text[index - 1].isalpha():
            return False
        return index == 1 or not text[index - 2].isalpha()

    @staticmethod
    def _number_continues_after_period(text: str, index: int) -> bool:
        if index == 0 or not text[index - 1].isdigit():
            return False
        next_index = index + 1
        while next_index < len(text) and text[next_index].isspace():
            next_index += 1
        return next_index < len(text) and text[next_index].isdigit()

    @classmethod
    def _trim_context(cls, sentence: str, span_start: int, span_length: int) -> str:
        leading_whitespace = len(sentence) - len(sentence.lstrip())
        sentence = sentence.strip()
        span_start -= leading_whitespace
        if len(sentence) <= cls._CONTEXT_LIMIT:
            return sentence
        span_start = max(0, min(span_start, len(sentence)))
        if span_length >= cls._CONTEXT_LIMIT:
            return sentence[span_start : span_start + cls._CONTEXT_LIMIT].strip()
        remaining = cls._CONTEXT_LIMIT - span_length
        start = span_start - remaining // 2
        start = max(0, min(start, len(sentence) - cls._CONTEXT_LIMIT))
        return sentence[start : start + cls._CONTEXT_LIMIT].strip()


FlagKind = Literal[
    "FACT",
    "FRAMING",
    "MOTIVE",
    "REMOVED_CONTEXT",
    "HIDDEN_TEXT",
    "CITATION_DATE",
    "CITED_PAGE",
]
FlagTier = Literal["admin", "review"]
FlagSide = Literal["new", "old"]
FlagCheck = Literal["judge", "stealth", "citation_dates", "render"]
FlagEvidenceSource = Literal["cited", "old", "new"]


class FlagEvidence(BaseModel):
    source: FlagEvidenceSource
    quote: str
    url: str | None = None


class Flag(BaseModel):
    id: str
    kind: FlagKind
    tier: FlagTier
    title: str = Field(max_length=80)
    reason: str
    confidence: float
    side: FlagSide
    anchor_text: str
    anchor_start: int | None
    anchor_end: int | None
    context_sentence: str
    evidence: list[FlagEvidence]
    citations: list[str]
    neutral_rewrite: str | None
    check: FlagCheck


class AuditOutput(BaseModel):
    verdict: Verdict
    confidence: float
    expand_direction: ExpandDirection
    atomic_propositions: list[AtomicProposition]
    flagged_spans: list[FlaggedSpan]
    neutral_rewrite: str | None


ExpectedLabel = Verdict | Literal["UNLABELLED"]


class Case(BaseModel):
    case_id: str
    lang: LangCode
    bucket: str
    provenance: str
    page_title: str
    old_text: str
    new_text: str
    ref_urls: list[str]
    old_wikitext: str | None = None
    new_wikitext: str | None = None
    changed_ref_urls: list[str] | None = None
    source_window: str | None = None
    expected: ExpectedLabel
    en_gloss: str | None = None
    notes: str = ""


class SourceWindow(BaseModel):
    url: str | None
    status: Literal["ok", "unavailable", "fixed", "uncited"]
    text: str
    latency_ms: float


class CaseResult(BaseModel):
    """Wrapper record: metadata lives here, never inside the section 10 output."""

    case_id: str
    model: str
    prompt_version: str
    stage_reached: int
    stage0_ms: float
    stage1_ms: float
    stage2_ms: float = 0.0
    source_status: str
    output: AuditOutput | None
    parse_error: str | None
    stealth_status: str | None = None
    stealth_vectors: list[str] = []
    stealth_ms: float = 0.0


def load_cases(path: Path) -> list[Case]:
    with path.open(encoding="utf-8") as f:
        return [Case.model_validate_json(line) for line in f if line.strip()]


def dump_jsonl(path: Path, rows: Sequence[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")

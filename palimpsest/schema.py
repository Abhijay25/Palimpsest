"""Audit output schema (spec section 10, fixed contract) and pipeline records."""

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


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
    lang: Literal["en", "fi"]
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

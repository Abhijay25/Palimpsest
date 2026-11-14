"""Selective-citation checks for sources whose later conclusion changes the picture."""

import json
import math
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final, Protocol

from google.genai import types
from pydantic import BaseModel, Field

from palimpsest.backends.gemini import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_JUDGE_THINKING,
    GeminiClient,
    _GeminiCaller,
)
from palimpsest.crosslingual import anchor_terms
from palimpsest.judge import _neutralise

PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "cherry_pick_v1.txt"
MAX_CHUNK_CHARS: Final = 700
MIN_PARAGRAPH_CHARS: Final = 80
_TOKEN_RE: Final = re.compile(r"[^\W\d_][\w'-]*|\d[\w'-]*", re.UNICODE)
_UNTRUSTED_SOURCE_TAG_RE: Final = re.compile(
    r"<(/?)\s*untrusted_source\b", re.IGNORECASE
)


class SourceChunk(BaseModel):
    """A stable, paragraph-oriented excerpt of a full source."""

    id: str
    index: int
    text: str


class CherryPickAnalysis(BaseModel):
    """Whether a citation omits a source's own material qualification."""

    is_cherry_picked: bool
    cherry_pick_confidence: float = Field(ge=0.0, le=1.0)
    cited_chunk_id: str
    contradicting_chunk_ids: list[str]
    source_overarching_conclusion: str
    omitted_qualifiers_summary: str
    balanced_npov_rewrite: str | None = None


class EvidenceSelection(BaseModel):
    """Source excerpts selected without relying on language-specific cues."""

    cited_chunk: SourceChunk
    conclusion_chunks: list[SourceChunk]
    related_chunks: list[SourceChunk]


class Embedder(Protocol):
    """Optional semantic-similarity hook for evidence ranking."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


JudgeCall = Callable[[str], Awaitable[CherryPickAnalysis]]


def _split_to_cap(text: str) -> list[str]:
    """Split a long paragraph at word boundaries while retaining all text."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = word
        else:
            current = candidate
        while len(current) > MAX_CHUNK_CHARS:
            pieces.append(current[:MAX_CHUNK_CHARS])
            current = current[MAX_CHUNK_CHARS:]
    if current:
        pieces.append(current)
    return pieces


def chunk_source(text: str) -> list[SourceChunk]:
    """Return stable paragraph chunks, joining short adjacent paragraphs when safe."""
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in re.split(r"\n\s*\n+", text)
        if paragraph.strip()
    ]
    merged: list[str] = []
    pending = ""
    for paragraph in paragraphs:
        if len(paragraph) < MIN_PARAGRAPH_CHARS:
            pending = f"{pending} {paragraph}".strip()
            continue
        if pending:
            combined = f"{pending} {paragraph}"
            if len(combined) <= MAX_CHUNK_CHARS:
                merged.append(combined)
            else:
                merged.append(pending)
                merged.append(paragraph)
            pending = ""
        else:
            merged.append(paragraph)
    if pending:
        if merged and len(f"{merged[-1]} {pending}") <= MAX_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]} {pending}"
        else:
            merged.append(pending)
    capped = [piece for paragraph in merged for piece in _split_to_cap(paragraph)]
    return [
        SourceChunk(id=f"c{index}", index=index, text=chunk)
        for index, chunk in enumerate(capped)
    ]


def _normalised_tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text)}


def _overlap_score(claim: str, chunk: str) -> float:
    claim_tokens = _normalised_tokens(claim)
    chunk_tokens = _normalised_tokens(chunk)
    lexical = len(claim_tokens & chunk_tokens) / math.sqrt(
        max(1, len(claim_tokens) * len(chunk_tokens))
    )
    claim_anchors = {anchor.casefold() for anchor in anchor_terms(claim)}
    chunk_anchors = {anchor.casefold() for anchor in anchor_terms(chunk)}
    anchors = len(claim_anchors & chunk_anchors) / math.sqrt(
        max(1, len(claim_anchors) * len(chunk_anchors))
    )
    return lexical + anchors


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return (
        sum(a * b for a, b in zip(left, right, strict=True)) / denominator
        if denominator
        else 0.0
    )


async def select_evidence(
    claim: str,
    chunks: list[SourceChunk],
    k: int = 3,
    embedder: Embedder | None = None,
) -> EvidenceSelection:
    """Choose cited, closing, and related excerpts using language-neutral similarity."""
    if not chunks:
        raise ValueError("Cannot select evidence from an empty source")
    scores = [_overlap_score(claim, chunk.text) for chunk in chunks]
    if embedder is not None:
        vectors = await embedder.embed([claim, *(chunk.text for chunk in chunks)])
        if len(vectors) != len(chunks) + 1:
            raise ValueError(
                "Embedder returned a vector count that does not match its inputs"
            )
        scores = [
            score + 0.25 * _cosine(vectors[0], vector)
            for score, vector in zip(scores, vectors[1:], strict=True)
        ]
    ranked = sorted(range(len(chunks)), key=lambda index: (-scores[index], index))
    cited_index = ranked[0]
    related = [chunks[index] for index in ranked if index != cited_index][: max(k, 0)]
    return EvidenceSelection(
        cited_chunk=chunks[cited_index],
        conclusion_chunks=chunks[-2:],
        related_chunks=related,
    )


def render_cherry_pick_payload(claim: str, evidence: EvidenceSelection) -> str:
    """Render source data so it cannot impersonate instructions or field boundaries."""
    data = json.dumps(
        {
            "claim": claim,
            "cited_chunk": evidence.cited_chunk.model_dump(),
            "conclusion_chunks": [
                chunk.model_dump() for chunk in evidence.conclusion_chunks
            ],
            "related_chunks": [chunk.model_dump() for chunk in evidence.related_chunks],
        },
        ensure_ascii=False,
    )
    safe = _UNTRUSTED_SOURCE_TAG_RE.sub(r"&lt;\1untrusted_source", data)
    return f"<untrusted_source>\n{_neutralise(safe)}\n</untrusted_source>"


def _not_cherry_picked() -> CherryPickAnalysis:
    return CherryPickAnalysis(
        is_cherry_picked=False,
        cherry_pick_confidence=0.0,
        cited_chunk_id="",
        contradicting_chunk_ids=[],
        source_overarching_conclusion="",
        omitted_qualifiers_summary="",
    )


async def analyze_cherry_pick(
    claim: str,
    source_text: str,
    judge_call: JudgeCall,
    embedder: Embedder | None = None,
) -> CherryPickAnalysis:
    """Ask one structured judge only when a full source has enough context to compare."""
    chunks = chunk_source(source_text)
    if len(chunks) < 3:
        return _not_cherry_picked()
    evidence = await select_evidence(claim, chunks, embedder=embedder)
    return await judge_call(render_cherry_pick_payload(claim, evidence))


class GeminiCherryPickBackend:
    """Callable structured judge backed by the shared Gemini retry/timeout wrapper."""

    name = "gemini_cherry_pick"

    def __init__(
        self,
        client: GeminiClient | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        model: str = DEFAULT_JUDGE_MODEL,
    ) -> None:
        self.model = model
        self._caller = _GeminiCaller(model, client, backoff_seconds)
        if self._caller.thinking is None:
            self._caller.thinking = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(DEFAULT_JUDGE_THINKING)
            )
        self._system = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def usage(self) -> dict[str, int]:
        return self._caller.usage

    async def __call__(self, payload: str) -> CherryPickAnalysis:
        result, _ = await self._caller.generate(
            self._system, payload, CherryPickAnalysis
        )
        if isinstance(result, str):
            raise TypeError(result)
        return result

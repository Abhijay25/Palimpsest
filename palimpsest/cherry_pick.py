"""Selective-citation checks for sources whose later conclusion changes the picture."""

import asyncio
import json
import math
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final, Literal, Protocol

from google.genai import types
from pydantic import BaseModel, Field

from palimpsest.backends.gemini import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_JUDGE_THINKING,
    GeminiClient,
    GeminiJudgeBackend,
    _GeminiCaller,
)
from palimpsest.cascade import CascadeJudgeBackend
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
    contradicting_passages: list[str] = Field(default_factory=list)


class CherryPickFinding(BaseModel):
    """One selective-citation finding safe to expose in an audit response."""

    unit_index: int
    claim: str
    source_passage: str
    citations: list[str]
    confidence: float
    tier: Literal["admin", "review"]
    balanced_rewrite: str | None = None


class CherryPickScan(BaseModel):
    """Best-effort B2 result; errors never affect the primary audit verdict."""

    status: Literal["ok", "skipped", "unavailable"]
    findings: list[CherryPickFinding] = Field(default_factory=list)
    error: str | None = None


class CherryPickCandidate(BaseModel):
    """A changed, cited edit unit whose source window was available to the judge."""

    unit_index: int
    claim: str
    url: str
    source_window: str
    citations: list[str]


class EvidenceSelection(BaseModel):
    """Source excerpts selected without relying on language-specific cues."""

    cited_chunk: SourceChunk
    conclusion_chunks: list[SourceChunk]
    related_chunks: list[SourceChunk]


class Embedder(Protocol):
    """Optional semantic-similarity hook for evidence ranking."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


JudgeCall = Callable[[str], Awaitable[CherryPickAnalysis]]


class CherryPickFetcher(Protocol):
    """The small SourceFetcher surface B2 needs after Stage 1 has succeeded."""

    def cached_text(self, url: str) -> str | None: ...

    async def source_text(self, url: str) -> str | None: ...

    async def highlights(self, url: str, query: str) -> list[str] | None: ...


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
    highlight_chunks: list[SourceChunk] | None = None,
) -> EvidenceSelection:
    """Choose cited and conclusion excerpts using language-neutral similarity.

    Exa highlights are query-selected source passages, so use them for the
    conclusion/qualifier context when available rather than guessing that a
    document's final paragraphs are its conclusion.
    """
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
    conclusions = highlight_chunks or chunks[-2:]
    return EvidenceSelection(
        cited_chunk=chunks[cited_index],
        conclusion_chunks=conclusions[: max(k, 0)],
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
    highlights: list[str] | None = None,
    require_context: bool = True,
) -> CherryPickAnalysis:
    """Ask one structured judge only when a full source has enough context to compare."""
    chunks = chunk_source(source_text)
    if len(chunks) < 3 and require_context:
        return _not_cherry_picked()
    if not chunks:
        return _not_cherry_picked()
    highlight_chunks = [
        SourceChunk(id=f"h{index}", index=index, text=highlight)
        for index, highlight in enumerate(highlights or [])
        if highlight.strip()
    ]
    evidence = await select_evidence(
        claim, chunks, embedder=embedder, highlight_chunks=highlight_chunks or None
    )
    return await judge_call(render_cherry_pick_payload(claim, evidence))


class GeminiCherryPickBackend:
    """Callable structured judge backed by the shared Gemini retry/timeout wrapper."""

    name = "gemini_cherry_pick"

    def __init__(
        self,
        client: GeminiClient | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        model: str = DEFAULT_JUDGE_MODEL,
        caller: _GeminiCaller | None = None,
    ) -> None:
        self.model = model
        self._caller = caller or _GeminiCaller(model, client, backoff_seconds)
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


def gemini_cherry_pick_judge(
    backend: object,
) -> GeminiCherryPickBackend | None:
    """Reuse the audit judge's caller, including its concurrency and timeout limits."""
    if isinstance(backend, GeminiJudgeBackend):
        return GeminiCherryPickBackend(model=backend.model, caller=backend._caller)
    if isinstance(backend, CascadeJudgeBackend):
        return gemini_cherry_pick_judge(backend.second)
    return None


async def scan_cherry_picks(
    candidates: list[CherryPickCandidate],
    fetcher: CherryPickFetcher,
    judge_call: JudgeCall | None,
) -> CherryPickScan:
    """Run one B2 call for each already-gated candidate without failing the audit."""
    if not candidates or judge_call is None:
        return CherryPickScan(status="skipped")

    async def one(
        candidate: CherryPickCandidate,
    ) -> CherryPickFinding | Exception | None:
        try:
            cached_text = fetcher.cached_text(candidate.url)
            fetched_text = (
                None
                if cached_text is not None
                else await fetcher.source_text(candidate.url)
            )
            source_text = cached_text or fetched_text or candidate.source_window
            highlights = await fetcher.highlights(candidate.url, candidate.claim)
            analysis = await analyze_cherry_pick(
                candidate.claim,
                source_text,
                judge_call,
                highlights=highlights,
                require_context=False,
            )
            if not analysis.is_cherry_picked:
                return None
            passage = next(iter(analysis.contradicting_passages), "")
            if not passage:
                chunks = {chunk.id: chunk.text for chunk in chunk_source(source_text)}
                passage = next(
                    (
                        chunks[chunk_id]
                        for chunk_id in analysis.contradicting_chunk_ids
                        if chunk_id in chunks
                    ),
                    analysis.source_overarching_conclusion,
                )
            direct_quote = bool(
                (cached_text or fetched_text)
                and passage
                and passage in (cached_text or fetched_text or "")
            )
            return CherryPickFinding(
                unit_index=candidate.unit_index,
                claim=candidate.claim,
                source_passage=passage,
                citations=candidate.citations,
                confidence=analysis.cherry_pick_confidence,
                tier="admin" if direct_quote else "review",
                balanced_rewrite=analysis.balanced_npov_rewrite,
            )
        except Exception as exc:  # noqa: BLE001 - individual source failures are isolated
            return exc

    results = await asyncio.gather(*(one(candidate) for candidate in candidates))
    errors = [
        f"{type(result).__name__}: {result}"
        for result in results
        if isinstance(result, Exception)
    ]
    findings = [result for result in results if isinstance(result, CherryPickFinding)]
    return CherryPickScan(
        status="unavailable" if len(errors) == len(candidates) else "ok",
        findings=findings,
        error="; ".join(errors) or None,
    )

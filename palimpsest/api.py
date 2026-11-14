"""FastAPI surface: stealth-scan, audit-diff (spec s2 contract) and healthz."""

import os
import time
from functools import cache
from typing import Annotated, Final, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import AfterValidator, BaseModel, Field

from palimpsest.backends.gemini import GeminiJudgeBackend
from palimpsest.judge import PreparedCase
from palimpsest.pipeline import (
    CACHE_DIR,
    _case_result,
    _stealth_status,
    _stealth_vectors,
    _window_for,
    _worst_scan,
)
from palimpsest.schema import (
    AtomicProposition,
    AuditOutput,
    Case,
    Verdict,
)
from palimpsest.scoring import ADMIN_FLAG_STATUSES, Route, route
from palimpsest.sources import DailyCallCap, SourceFetcher, load_exa_api_key
from palimpsest.stage0 import prefilter, refs_for_changed_sentences
from palimpsest.stealth.models import ScanResult
from palimpsest.stealth.scanner import TargetType, scan

MAX_TEXT_CHARS: Final = 200_000
MAX_REF_URLS: Final = 50
# Placeholder rule only: the real trust model lives with the editor-profile service.
TRUST_DELTA_BY_VERDICT: Final = {
    Verdict.FLAG_G1_FACT: -0.10,
    Verdict.FLAG_G2_FRAMING: -0.05,
    Verdict.FLAG_G3_MOTIVE: -0.08,
}
TRUST_DELTA_STEALTH_ADMIN: Final = -0.20

app = FastAPI(title="Palimpsest", version="0.1.0")


@cache
def _shared_fetcher() -> SourceFetcher:
    return SourceFetcher(load_exa_api_key(), CACHE_DIR, daily_cap=DailyCallCap())


def get_fetcher() -> SourceFetcher:
    """Per-request fetcher: its own Exa budget, sharing the process-wide daily cap."""
    return _shared_fetcher().for_request()


@cache
def get_judge_backend() -> GeminiJudgeBackend | None:
    """Gemini judge when GEMINI_API_KEY is set, else None (never faked)."""
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    return GeminiJudgeBackend()


def _http_url(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("ref_urls entries must be http(s) URLs")
    return url


Text = Annotated[str, Field(max_length=MAX_TEXT_CHARS)]


class StealthScanRequest(BaseModel):
    text: Text
    target_type: TargetType
    old_text: Text | None = None


class AuditDiffRequest(BaseModel):
    lang_code: Literal["en", "fi"]
    page_title: str = Field(min_length=1, max_length=512)
    section_title: str | None = Field(default=None, max_length=512)
    old_revision_id: int = Field(ge=0)
    new_revision_id: int = Field(ge=0)
    editor_username: str = Field(min_length=1, max_length=512)
    old_text: Text
    new_text: Text
    ref_urls: list[Annotated[str, AfterValidator(_http_url)]] = Field(
        max_length=MAX_REF_URLS
    )
    old_wikitext: Text | None = None
    new_wikitext: Text | None = None


class SpanOut(BaseModel):
    exact_substring: str
    guideline_violated: str
    explanation: str
    start: int | None
    end: int | None


class StealthSummary(BaseModel):
    status: str
    vectors: list[str]
    finding_count: int


class LatencyMs(BaseModel):
    stealth: float
    stage0: float
    stage1: float
    stage2: float
    total: float


class AuditDiffResponse(BaseModel):
    verdict: Verdict
    confidence: float
    flagged_spans: list[SpanOut]
    atomic_propositions: list[AtomicProposition]
    neutral_rewrite: str | None
    editor_trust_delta: float
    route: Route
    pipeline_stage_reached: Literal[0, 1, 2]
    stealth: StealthSummary
    latency_ms: LatencyMs
    exa_budget_exhausted: bool


class HealthResponse(BaseModel):
    judge_configured: bool
    exa_configured: bool


def _trust_delta(output: AuditOutput, stealth_flagged: bool) -> float:
    if stealth_flagged:
        return TRUST_DELTA_STEALTH_ADMIN
    return TRUST_DELTA_BY_VERDICT.get(output.verdict, 0.0)


def _spans_with_offsets(output: AuditOutput, new_text: str) -> list[SpanOut]:
    spans: list[SpanOut] = []
    for span in output.flagged_spans:
        start = new_text.find(span.exact_substring) if span.exact_substring else -1
        found = start >= 0
        spans.append(
            SpanOut(
                exact_substring=span.exact_substring,
                guideline_violated=span.guideline_violated.value,
                explanation=span.explanation,
                start=start if found else None,
                end=start + len(span.exact_substring) if found else None,
            )
        )
    return spans


@app.get("/healthz", response_model=HealthResponse)
def healthz(
    backend: Annotated[GeminiJudgeBackend | None, Depends(get_judge_backend)],
) -> HealthResponse:
    load_dotenv()
    return HealthResponse(
        judge_configured=backend is not None,
        exa_configured=load_exa_api_key() is not None,
    )


@app.post("/api/v1/stealth-scan", response_model=ScanResult)
def stealth_scan(req: StealthScanRequest) -> ScanResult:
    return scan(req.text, req.target_type, old_text=req.old_text)


def _scan_request(
    req: AuditDiffRequest,
) -> tuple[ScanResult, ScanResult, ScanResult, list[str] | None]:
    """CPU-bound scans for one request; run off the event loop."""
    diff_scan = scan(
        req.new_wikitext or req.new_text,
        "WIKIPEDIA_DIFF",
        old_text=req.old_wikitext or req.old_text,
    )
    old_scan = scan(req.old_text, "WIKIPEDIA_DIFF")
    new_scan = scan(req.new_text, "WIKIPEDIA_DIFF")
    changed_refs = (
        refs_for_changed_sentences(req.old_wikitext, req.new_wikitext)
        if req.old_wikitext and req.new_wikitext
        else None
    )
    return diff_scan, old_scan, new_scan, changed_refs


@app.post("/api/v1/audit-diff", response_model=AuditDiffResponse)
async def audit_diff(
    req: AuditDiffRequest,
    fetcher: Annotated[SourceFetcher, Depends(get_fetcher)],
    backend: Annotated[GeminiJudgeBackend | None, Depends(get_judge_backend)],
) -> AuditDiffResponse:
    started = time.perf_counter()
    diff_scan, old_scan, new_scan, changed_refs = await run_in_threadpool(
        _scan_request, req
    )
    stealth_ms = (
        diff_scan.scan_latency_ms + old_scan.scan_latency_ms + new_scan.scan_latency_ms
    )
    case = Case(
        case_id=f"{req.lang_code}:{req.page_title}:{req.new_revision_id}",
        lang=req.lang_code,
        bucket="api",
        provenance="api",
        page_title=req.page_title,
        old_text=old_scan.sanitized_human_text,
        new_text=new_scan.sanitized_human_text,
        ref_urls=req.ref_urls,
        old_wikitext=req.old_wikitext,
        new_wikitext=req.new_wikitext,
        changed_ref_urls=changed_refs,
        expected="UNLABELLED",
    )
    stage0 = await run_in_threadpool(prefilter, case.old_text, case.new_text, case.lang)
    pc = PreparedCase(
        case=case,
        stage0=stage0,
        window=None,
        diff_scan=diff_scan,
        stealth_ms=stealth_ms,
    )
    judged: dict[str, AuditOutput | str] = {}
    stage2_ms = 0.0
    if not stage0.clean:
        if backend is None:
            raise HTTPException(
                status_code=503,
                detail="Judge backend unavailable: set GEMINI_API_KEY to enable "
                "Stage 2. No verdict was produced.",
            )
        ref_scans: list[ScanResult] = []
        pc.window = await _window_for(case, fetcher, ref_scans)
        pc.ref_scan = _worst_scan(ref_scans)
        pc.stealth_ms += sum(s.scan_latency_ms for s in ref_scans)
        judged = await backend.judge([pc])
        stage2_ms = backend.latencies_ms.get(case.case_id, 0.0)
        outcome = judged.get(case.case_id, "no result for this case")
        if isinstance(outcome, str):
            raise HTTPException(
                status_code=502, detail=f"Judge backend failed: {outcome}"
            )
    result = _case_result(
        pc, backend.model if backend else "none", judged, "api", stage2_ms
    )
    output = result.output
    if output is None:
        raise HTTPException(status_code=500, detail="No audit output produced.")
    stealth_flagged = pc.diff_scan is not None and (
        pc.diff_scan.stealth_status in ADMIN_FLAG_STATUSES
    )
    return AuditDiffResponse(
        verdict=output.verdict,
        confidence=output.confidence,
        flagged_spans=_spans_with_offsets(output, req.new_text),
        atomic_propositions=output.atomic_propositions,
        neutral_rewrite=output.neutral_rewrite,
        editor_trust_delta=_trust_delta(output, stealth_flagged),
        route=route(result),
        pipeline_stage_reached=result.stage_reached,
        stealth=StealthSummary(
            status=_stealth_status(pc) or "CLEAN",
            vectors=_stealth_vectors(pc),
            finding_count=sum(
                len(s.hidden_findings) for s in (pc.diff_scan, pc.ref_scan) if s
            ),
        ),
        latency_ms=LatencyMs(
            stealth=pc.stealth_ms,
            stage0=stage0.latency_ms,
            stage1=pc.window.latency_ms if pc.window else 0.0,
            stage2=stage2_ms,
            total=(time.perf_counter() - started) * 1000,
        ),
        exa_budget_exhausted=fetcher.budget_exhausted,
    )

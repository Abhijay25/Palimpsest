"""FastAPI surface: stealth-scan, audit-diff (spec s2 contract) and healthz."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from functools import cache
from typing import Annotated, Final, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import AfterValidator, BaseModel, Field

from palimpsest.backends.gemini import GeminiJudgeBackend, gemini_enabled
from palimpsest.judge import PreparedCase
from palimpsest.pipeline import (
    CACHE_DIR,
    _case_result,
    _stealth_status,
    _stealth_vectors,
    _window_for,
    _worst_scan,
)
from palimpsest.render_service import (
    AuditorProvider,
    RenderSummary,
    close_shared_auditor,
    scan_ref_pages_in_temp_dir,
    shared_auditor,
)
from palimpsest.schema import (
    AtomicProposition,
    AuditOutput,
    Case,
    CaseResult,
    LangCode,
    Verdict,
)
from palimpsest.scoring import ADMIN_FLAG_STATUSES, FLAGS, Route, route
from palimpsest.segment import EditUnit, changed_chars, split_edit
from palimpsest.sources import DailyCallCap, SourceFetcher, load_exa_api_key
from palimpsest.stage0 import prefilter, refs_for_changed_sentences
from palimpsest.stealth.models import ScanResult, StealthStatus
from palimpsest.stealth.scanner import TargetType, scan, worst_status

MAX_TEXT_CHARS: Final = 200_000
MAX_REF_URLS: Final = 50
UNIT_CONCURRENCY: Final = 4
MAX_UNITS: Final = 12
ROUTE_RANK: Final[dict[Route, int]] = {"none": 0, "review": 1, "admin": 2}
# Placeholder rule only: the real trust model lives with the editor-profile service.
TRUST_DELTA_BY_VERDICT: Final = {
    Verdict.FLAG_G1_FACT: -0.10,
    Verdict.FLAG_G2_FRAMING: -0.05,
    Verdict.FLAG_G3_MOTIVE: -0.08,
}
TRUST_DELTA_STEALTH_ADMIN: Final = -0.20


@contextlib.asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_shared_auditor()


app = FastAPI(title="Palimpsest", version="0.1.0", lifespan=_lifespan)


def get_auditor_provider() -> AuditorProvider:
    """Lazy provider of the shared page renderer (overridable in tests)."""
    return shared_auditor


@cache
def _shared_fetcher() -> SourceFetcher:
    return SourceFetcher(load_exa_api_key(), CACHE_DIR, daily_cap=DailyCallCap())


def get_fetcher() -> SourceFetcher:
    """Per-request fetcher: its own Exa budget, sharing the process-wide daily cap."""
    return _shared_fetcher().for_request()


@cache
def get_judge_backend() -> GeminiJudgeBackend | None:
    """Gemini judge when GEMINI_API_KEY is set and opted in, else None (never faked)."""
    if not gemini_enabled():
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
    lang_code: LangCode
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
    occurrences: int


class StealthSummary(BaseModel):
    status: str
    vectors: list[str]
    finding_count: int


class LatencyMs(BaseModel):
    stealth: float
    stage0: float
    stage1: float
    stage2: float
    render: float
    total: float


class UnitSummary(BaseModel):
    index: int
    kind: Literal["changed", "inserted", "deleted"]
    verdict: Verdict
    confidence: float
    route: Route
    stage_reached: Literal[0, 1, 2]
    latency_ms: float


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
    render: RenderSummary
    latency_ms: LatencyMs
    exa_budget_exhausted: bool
    units: list[UnitSummary]
    partial: bool


class HealthResponse(BaseModel):
    judge_configured: bool
    exa_configured: bool


def _trust_delta(output: AuditOutput, stealth_flagged: bool) -> float:
    if stealth_flagged:
        return TRUST_DELTA_STEALTH_ADMIN
    return TRUST_DELTA_BY_VERDICT.get(output.verdict, 0.0)


def _raw_index_map(raw_length: int, removed: list[tuple[int, int]]) -> list[int]:
    """Raw-text index of each character that survives removal of the given spans."""
    kept: list[int] = []
    cursor = 0
    for start, end in sorted(removed):
        kept.extend(range(cursor, max(cursor, start)))
        cursor = max(cursor, end)
    kept.extend(range(cursor, raw_length))
    return kept


def _spans_with_offsets(
    output: AuditOutput, new_scan: ScanResult, raw: str
) -> list[SpanOut]:
    """First-match offsets into the raw text, found in the sanitized text the judge saw."""
    sanitized = new_scan.sanitized_human_text
    index_map = _raw_index_map(len(raw), new_scan.removed_spans)
    spans: list[SpanOut] = []
    for span in output.flagged_spans:
        needle = span.exact_substring
        start = sanitized.find(needle) if needle else -1
        found = start >= 0 and len(index_map) == len(sanitized)
        spans.append(
            SpanOut(
                exact_substring=needle,
                guideline_violated=span.guideline_violated.value,
                explanation=span.explanation,
                start=index_map[start] if found else None,
                end=index_map[start + len(needle) - 1] + 1 if found else None,
                occurrences=sanitized.count(needle) if needle else 0,
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
) -> tuple[ScanResult, ScanResult, ScanResult, list[EditUnit]]:
    """CPU-bound scans for one request; run off the event loop."""
    diff_scan = scan(
        req.new_wikitext or req.new_text,
        "WIKIPEDIA_DIFF",
        old_text=req.old_wikitext or req.old_text,
    )
    old_scan = scan(req.old_text, "WIKIPEDIA_DIFF")
    new_scan = scan(req.new_text, "WIKIPEDIA_DIFF")
    units = _units_for(req, old_scan, new_scan)
    return diff_scan, old_scan, new_scan, units


def _units_for(
    req: AuditDiffRequest, old_scan: ScanResult, new_scan: ScanResult
) -> list[EditUnit]:
    """Changed units of the sanitised texts; one whole-edit unit if nothing aligns."""
    old_text = old_scan.sanitized_human_text
    new_text = new_scan.sanitized_human_text
    units = split_edit(old_text, new_text, req.old_wikitext, req.new_wikitext)
    if not units:
        return [
            EditUnit(
                index=0,
                old_text=old_text,
                new_text=new_text,
                old_wikitext=req.old_wikitext,
                new_wikitext=req.new_wikitext,
                kind="changed",
            )
        ]
    if len(units) == 1 and (units[0].old_text, units[0].new_text) == (
        old_text,
        new_text,
    ):
        return units
    # Unit text derived from raw wikitext must pass the same sanitiser the judge relies on.
    return [
        u.model_copy(
            update={
                "old_text": scan(u.old_text, "WIKIPEDIA_DIFF").sanitized_human_text,
                "new_text": scan(u.new_text, "WIKIPEDIA_DIFF").sanitized_human_text,
            }
        )
        for u in units
    ]


async def _await_render(task: "asyncio.Task[RenderSummary]") -> RenderSummary:
    """Render failures degrade to an unavailable summary; they never fail the audit."""
    try:
        return await task
    except Exception:  # noqa: BLE001 - render scan is best-effort
        return RenderSummary(status="unavailable")


class _UnitOutcome(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    unit: EditUnit
    pc: PreparedCase
    result: CaseResult
    output: AuditOutput
    stage2_ms: float
    unit_ms: float


def _unit_changed_refs(unit: EditUnit) -> list[str] | None:
    if unit.old_wikitext and unit.new_wikitext:
        return refs_for_changed_sentences(unit.old_wikitext, unit.new_wikitext)
    return None


def _verdict_rank(output: AuditOutput) -> int:
    if output.verdict in FLAGS:
        return 2
    return 1 if output.verdict == Verdict.EXPAND_CONTEXT else 0


async def _judge_unit(
    req: AuditDiffRequest,
    unit: EditUnit,
    changed_refs: list[str] | None,
    diff_scan: ScanResult,
    fetcher: SourceFetcher,
    backend: GeminiJudgeBackend | None,
    semaphore: asyncio.Semaphore,
) -> _UnitOutcome:
    async with semaphore:
        started = time.perf_counter()
        case = Case(
            case_id=f"{req.lang_code}:{req.page_title}:{req.new_revision_id}"
            f"#u{unit.index}",
            lang=req.lang_code,
            bucket="api",
            provenance="api",
            page_title=req.page_title,
            old_text=unit.old_text,
            new_text=unit.new_text,
            ref_urls=req.ref_urls,
            old_wikitext=unit.old_wikitext,
            new_wikitext=unit.new_wikitext,
            changed_ref_urls=changed_refs,
            expected="UNLABELLED",
        )
        stage0 = await run_in_threadpool(
            prefilter, case.old_text, case.new_text, case.lang
        )
        pc = PreparedCase(case=case, stage0=stage0, window=None, diff_scan=diff_scan)
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
            pc.stealth_ms = sum(s.scan_latency_ms for s in ref_scans)
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
        if result.output is None:
            raise HTTPException(status_code=500, detail="No audit output produced.")
        return _UnitOutcome(
            unit=unit,
            pc=pc,
            result=result,
            output=result.output,
            stage2_ms=stage2_ms,
            unit_ms=(time.perf_counter() - started) * 1000,
        )


async def _cancel_all(tasks: "list[asyncio.Task[_UnitOutcome]]") -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(BaseException):
            await task


@app.post("/api/v1/audit-diff", response_model=AuditDiffResponse)
async def audit_diff(
    req: AuditDiffRequest,
    fetcher: Annotated[SourceFetcher, Depends(get_fetcher)],
    backend: Annotated[GeminiJudgeBackend | None, Depends(get_judge_backend)],
    auditor_provider: Annotated[AuditorProvider, Depends(get_auditor_provider)],
) -> AuditDiffResponse:
    started = time.perf_counter()
    diff_scan, old_scan, new_scan, all_units = await run_in_threadpool(
        _scan_request, req
    )
    stealth_ms = (
        diff_scan.scan_latency_ms + old_scan.scan_latency_ms + new_scan.scan_latency_ms
    )
    partial = len(all_units) > MAX_UNITS
    units = all_units
    if partial:
        top = sorted(all_units, key=lambda u: (-changed_chars(u), u.index))[:MAX_UNITS]
        units = sorted(top, key=lambda u: u.index)
    refs_by_unit = {u.index: _unit_changed_refs(u) for u in units}
    union_refs: list[str] = []
    for unit in units:
        for url in (
            req.ref_urls
            if refs_by_unit[unit.index] is None
            else refs_by_unit[unit.index]
        ) or []:
            if url not in union_refs:
                union_refs.append(url)
    render_task = asyncio.create_task(
        scan_ref_pages_in_temp_dir(
            union_refs or req.ref_urls, auditor_provider, fetcher.cached_text
        )
    )
    semaphore = asyncio.Semaphore(UNIT_CONCURRENCY)
    unit_tasks = [
        asyncio.create_task(
            _judge_unit(
                req,
                unit,
                refs_by_unit[unit.index],
                diff_scan,
                fetcher,
                backend,
                semaphore,
            )
        )
        for unit in units
    ]
    try:
        try:
            outcomes = list(await asyncio.gather(*unit_tasks))
        except BaseException:
            await _cancel_all(unit_tasks)
            raise
        top_outcome = max(
            outcomes,
            key=lambda o: (
                _verdict_rank(o.output),
                o.output.confidence if _verdict_rank(o.output) == 2 else 0.0,
                -o.unit.index,
            ),
        )
        output = top_outcome.output
        stealth_flagged = diff_scan.stealth_status in ADMIN_FLAG_STATUSES
        render = await _await_render(render_task)
        unit_routes: list[Route] = [route(o.result) for o in outcomes]
        top_route = max(unit_routes, key=ROUTE_RANK.__getitem__)
        if render.escalate:
            top_route = "admin"
        elif partial and top_route == "none":
            top_route = "review"
        contributing = [o for o in outcomes if o.output.verdict in FLAGS] or [
            top_outcome
        ]
        stealth_statuses = [
            s for o in outcomes if (s := _stealth_status(o.pc)) is not None
        ]
        ref_findings = sum(
            len(o.pc.ref_scan.hidden_findings) for o in outcomes if o.pc.ref_scan
        )
        ref_scan_ms = sum(o.pc.stealth_ms for o in outcomes)
        return AuditDiffResponse(
            verdict=output.verdict,
            confidence=output.confidence,
            flagged_spans=[
                span
                for o in contributing
                for span in _spans_with_offsets(o.output, new_scan, req.new_text)
            ],
            atomic_propositions=output.atomic_propositions,
            neutral_rewrite=output.neutral_rewrite,
            editor_trust_delta=_trust_delta(output, stealth_flagged),
            route=top_route,
            pipeline_stage_reached=max(o.result.stage_reached for o in outcomes),
            stealth=StealthSummary(
                status=(
                    worst_status(StealthStatus(s) for s in stealth_statuses).value
                    if stealth_statuses
                    else "CLEAN"
                ),
                vectors=sorted({v for o in outcomes for v in _stealth_vectors(o.pc)}),
                finding_count=len(diff_scan.hidden_findings) + ref_findings,
            ),
            render=render,
            latency_ms=LatencyMs(
                stealth=stealth_ms + ref_scan_ms,
                stage0=max(o.pc.stage0.latency_ms for o in outcomes),
                stage1=max(
                    o.pc.window.latency_ms if o.pc.window else 0.0 for o in outcomes
                ),
                stage2=max(o.stage2_ms for o in outcomes),
                render=render.latency_ms,
                total=(time.perf_counter() - started) * 1000,
            ),
            exa_budget_exhausted=fetcher.budget_exhausted,
            units=[
                UnitSummary(
                    index=o.unit.index,
                    kind=o.unit.kind,
                    verdict=o.output.verdict,
                    confidence=o.output.confidence,
                    route=r,
                    stage_reached=o.result.stage_reached,
                    latency_ms=o.unit_ms,
                )
                for o, r in zip(outcomes, unit_routes, strict=True)
            ],
            partial=partial,
        )
    except BaseException:
        render_task.cancel()
        with contextlib.suppress(BaseException):
            await render_task
        raise

"""FastAPI surface: stealth-scan, audit-diff (spec s2 contract) and healthz."""

import asyncio
import contextlib
import os
import re
import time
from collections.abc import AsyncIterator
from functools import cache
from typing import Annotated, Final, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import AfterValidator, BaseModel, Field

from palimpsest.backends.gemini import GeminiJudgeBackend, gemini_enabled
from palimpsest.cascade import CascadeJudgeBackend
from palimpsest.citation_dates import CitationDateScan, scan_changed_citation_dates
from palimpsest.crosslingual import CrossLingualReport, cross_lingual_fanout
from palimpsest.flags import JudgeFlagInput, StealthFlagInput, build_flags
from palimpsest.judge import (
    PROMPT_VERSION,
    AsyncJudge,
    PreparedCase,
    judge_with_latencies,
)
from palimpsest.pipeline import (
    CACHE_DIR,
    _case_result,
    _stealth_status,
    _stealth_vectors,
    _window_for,
    _worst_scan,
)
from palimpsest.reasons import REASON_TEXT, ReasonCode, reason_code
from palimpsest.render_service import (
    AuditorProvider,
    RenderedPages,
    RenderSummary,
    close_shared_auditor,
    render_ref_pages_in_temp_dir,
    shared_auditor,
    summarize_render,
)
from palimpsest.schema import (
    AtomicProposition,
    AuditOutput,
    Case,
    CaseResult,
    DisplayFlaggedSpan,
    Entailment,
    Flag,
    FlagEvidence,
    FlagTier,
    LangCode,
    SourceWindow,
    Verdict,
)
from palimpsest.scoring import ADMIN_FLAG_STATUSES, FLAGS, Route, route
from palimpsest.segment import EditUnit, changed_chars, split_edit
from palimpsest.sources import DailyCallCap, SourceFetcher, load_exa_api_key
from palimpsest.stage0 import prefilter, refs_for_changed_sentences
from palimpsest.stealth.models import ScanResult, StealthStatus
from palimpsest.stealth.scanner import (
    TargetType,
    reportable_findings,
    scan,
    worst_status,
)

MAX_TEXT_CHARS: Final = 200_000
MAX_REF_URLS: Final = 50
UNIT_CONCURRENCY: Final = 4
MAX_UNITS: Final = 12
# New and replaced text can each need a highlights view, plus one bounded follow-up.
EXA_CALLS_PER_UNIT: Final = 7
MAX_REQUEST_EXA_CALLS: Final = 28
ROUTE_RANK: Final[dict[Route, int]] = {"none": 0, "review": 1, "admin": 2}
# Placeholder rule only: the real trust model lives with the editor-profile service.
TRUST_DELTA_BY_VERDICT: Final = {
    Verdict.FLAG_G1_FACT: -0.10,
    Verdict.FLAG_G2_FRAMING: -0.05,
    Verdict.FLAG_G3_MOTIVE: -0.08,
}
TRUST_DELTA_STEALTH_ADMIN: Final = -0.20
CITATION_DATES_TIMEOUT_S: Final = 5.0
_CITATION_WIKITEXT_RE: Final = re.compile(r"{{|<ref\b", re.IGNORECASE)
_CHANGED_VALUE_RE: Final = re.compile(
    r"\b(?:\d[\d,.%]*|[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)\b"
)


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
    """Process-wide fetcher; audit_diff derives a per-request budget from it."""
    return _shared_fetcher()


@cache
def get_judge_backend() -> AsyncJudge | None:
    """Gemini judge when GEMINI_API_KEY is set and opted in, else None (never faked).

    With GEMINI_FIRST_PASS_MODEL set, a cheap first pass judges every unit and
    only its flags go to the main judge (CascadeJudgeBackend).
    """
    if not gemini_enabled():
        return None
    prompt_version = os.environ.get("PALIMPSEST_PROMPT", PROMPT_VERSION)
    main = GeminiJudgeBackend(prompt_version=prompt_version)
    first_model = os.environ.get("GEMINI_FIRST_PASS_MODEL")
    if first_model:
        return CascadeJudgeBackend(
            GeminiJudgeBackend(model=first_model, prompt_version=prompt_version), main
        )
    return main


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


class CrossLingualRequest(BaseModel):
    lang_code: LangCode
    page_title: str = Field(min_length=1, max_length=512)
    claim_text: Text
    edit_verdict: Verdict


class SpanOut(BaseModel):
    exact_substring: str
    guideline_violated: str
    explanation: str
    context_sentence: str | None
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
    reason: ReasonCode | None = None


class AuditDiffResponse(BaseModel):
    verdict: Verdict
    confidence: float
    reason: ReasonCode | None
    reason_text: str | None
    flags: list[Flag]
    flagged_spans: list[SpanOut]
    atomic_propositions: list[AtomicProposition]
    neutral_rewrite: str | None
    editor_trust_delta: float
    route: Route
    pipeline_stage_reached: Literal[0, 1, 2]
    stealth: StealthSummary
    render: RenderSummary
    citation_dates: CitationDateScan
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


def _flag_tier(unit_route: Route) -> FlagTier:
    """A response flag always needs a queue tier; unrouted findings remain reviewable."""
    return "admin" if unit_route == "admin" else "review"


def _stealth_flag_tier(status: StealthStatus) -> FlagTier:
    return "admin" if status in ADMIN_FLAG_STATUSES else "review"


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
    output: AuditOutput,
    new_scan: ScanResult,
    raw: str,
    unit_region: tuple[int, int] | None = None,
    judged_text: str | None = None,
    previous_judged_text: str | None = None,
) -> list[SpanOut]:
    """First-match offsets into the raw text, found in the sanitized text the judge saw.

    The unit's own region of the sanitized text is searched first (then the whole
    text), so a phrase repeated elsewhere in the edit does not steal the match.
    The API supplies only the judged unit's region.
    """
    sanitized = new_scan.sanitized_human_text
    index_map = _raw_index_map(len(raw), new_scan.removed_spans)
    region = unit_region or (0, len(sanitized))
    spans: list[SpanOut] = []
    for span in output.flagged_spans:
        needle = span.exact_substring
        start, occurrences = -1, 0
        if needle:
            lo, hi = region
            inside = sanitized[lo:hi]
            if needle in inside:
                start = lo + inside.find(needle)
                occurrences = inside.count(needle)
        found = start >= 0 and len(index_map) == len(sanitized)
        spans.append(
            SpanOut(
                exact_substring=needle,
                guideline_violated=span.guideline_violated.value,
                explanation=span.explanation,
                context_sentence=(
                    DisplayFlaggedSpan.context_for(judged_text, needle)
                    if judged_text is not None
                    else None
                )
                or (
                    DisplayFlaggedSpan.context_for(previous_judged_text, needle)
                    if previous_judged_text is not None
                    else None
                ),
                start=index_map[start] if found else None,
                end=index_map[start + len(needle) - 1] + 1 if found else None,
                occurrences=occurrences,
            )
        )
    return spans


def _unit_regions(
    new_scan: ScanResult, units: list[EditUnit]
) -> dict[int, tuple[int, int]]:
    """Locate each changed unit in order in the sanitized new revision.

    Advancing the cursor makes repeated paragraph text unambiguous. A unit that
    cannot be located receives no offsets rather than borrowing a match from a
    different part of the edit.
    """
    regions: dict[int, tuple[int, int]] = {}
    cursor = 0
    for unit in units:
        if not unit.new_text:
            continue
        start = new_scan.sanitized_human_text.find(unit.new_text, cursor)
        if start < 0:
            continue
        end = start + len(unit.new_text)
        regions[unit.index] = (start, end)
        cursor = end
    return regions


@app.get("/healthz", response_model=HealthResponse)
def healthz(
    backend: Annotated[AsyncJudge | None, Depends(get_judge_backend)],
) -> HealthResponse:
    load_dotenv()
    return HealthResponse(
        judge_configured=backend is not None,
        exa_configured=load_exa_api_key() is not None,
    )


@app.post("/api/v1/stealth-scan", response_model=ScanResult)
def stealth_scan(req: StealthScanRequest) -> ScanResult:
    return scan(req.text, req.target_type, old_text=req.old_text)


@app.post("/api/v1/cross-lingual", response_model=CrossLingualReport)
async def cross_lingual(
    req: CrossLingualRequest,
    fetcher: Annotated[SourceFetcher, Depends(get_fetcher)],
    backend: Annotated[AsyncJudge | None, Depends(get_judge_backend)],
) -> CrossLingualReport:
    """Run the explicit, slow cross-wiki audit; audit-diff never invokes this."""
    if backend is None:
        raise HTTPException(
            status_code=503,
            detail="Judge backend unavailable: set GEMINI_API_KEY to enable Stage 2.",
        )
    return await cross_lingual_fanout(
        req.lang_code,
        req.page_title,
        req.claim_text,
        req.edit_verdict,
        backend,
        fetcher,
    )


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


async def _await_render(task: "asyncio.Task[RenderedPages]") -> RenderedPages:
    """Render failures degrade to an unavailable result; they never fail the audit."""
    try:
        return await task
    except Exception:  # noqa: BLE001 - render scan is best-effort
        return RenderedPages(status="unavailable")


async def _await_completed_citation_dates(
    task: "asyncio.Task[CitationDateScan]",
    started_at: float,
) -> CitationDateScan:
    """Await only the scan time left after the units have finished."""
    remaining = started_at + CITATION_DATES_TIMEOUT_S - time.monotonic()
    if remaining <= 0 and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return CitationDateScan(status="unavailable", error="TimeoutError")
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=max(remaining, 0))
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return CitationDateScan(status="unavailable", error="TimeoutError")
    except Exception as exc:  # noqa: BLE001 - deterministic check is escalation-only
        return CitationDateScan(
            status="unavailable", error=f"{type(exc).__name__}: {exc}"
        )


def _citation_wikitexts(units: list[EditUnit]) -> list[str]:
    return [
        wikitext
        for unit in units
        if (wikitext := unit.new_wikitext or unit.new_text) is not None
        and _CITATION_WIKITEXT_RE.search(wikitext)
    ]


async def _scan_citation_dates(
    lang_code: str,
    page_title: str,
    wikitexts: list[str],
    started: "asyncio.Future[float]",
) -> CitationDateScan:
    """Mark the deadline when this task, rather than its creator, starts."""
    started.set_result(time.monotonic())
    return await scan_changed_citation_dates(lang_code, page_title, wikitexts)


class _UnitOutcome(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    unit: EditUnit
    pc: PreparedCase
    result: CaseResult
    output: AuditOutput
    stage2_ms: float
    unit_ms: float


class JudgeUnavailableError(Exception):
    """Stage 0 completed, but no configured judge can continue the audit."""

    def __init__(self, stage0_ms: float) -> None:
        self.stage0_ms = stage0_ms
        self.stealth_status = "CLEAN"
        self.finding_count = 0
        self.stealth_ms = 0.0
        super().__init__("Judge backend unavailable: no verdict was produced.")


def _unit_changed_refs(unit: EditUnit) -> list[str] | None:
    if unit.old_wikitext and unit.new_wikitext:
        return refs_for_changed_sentences(unit.old_wikitext, unit.new_wikitext)
    return None


def _verdict_rank(output: AuditOutput) -> int:
    if output.verdict in FLAGS:
        return 2
    return 1 if output.verdict == Verdict.EXPAND_CONTEXT else 0


def _followup_enabled() -> bool:
    return os.environ.get("PALIMPSEST_FOLLOWUP", "1") not in {"0", "false", "False"}


def _followup_query(unit: EditUnit) -> str | None:
    """Use values and named entities from the changed span, not page boilerplate."""
    values = list(dict.fromkeys(_CHANGED_VALUE_RE.findall(unit.new_text)))
    return " ".join(values) if values else None


def _needs_followup(output: AuditOutput) -> bool:
    return output.verdict == Verdict.EXPAND_CONTEXT or (
        output.verdict == Verdict.CLEAN_PASS
        and any(
            proposition.source_entailment == Entailment.UNSUPPORTED_EXTRAPOLATION
            for proposition in output.atomic_propositions
        )
    )


def _append_highlights(window: SourceWindow, highlights: list[str]) -> SourceWindow:
    existing = window.text.rstrip()
    first_index = existing.count("[Highlight ") + 1
    extra = "\n\n".join(
        f"[Highlight {index}]\n{highlight.strip()}"
        for index, highlight in enumerate(highlights, start=first_index)
        if highlight.strip() and highlight.strip() not in existing
    )
    if not extra:
        return window
    return window.model_copy(update={"text": f"{existing}\n\n{extra}"})


async def _maybe_followup_judge(
    fetcher: SourceFetcher,
    backend: AsyncJudge,
    pc: PreparedCase,
    unit: EditUnit,
    outcome: AuditOutput,
) -> tuple[AuditOutput, float]:
    """Append one targeted highlights view and re-judge at most once."""
    if (
        not _followup_enabled()
        or not _needs_followup(outcome)
        or pc.window is None
        or pc.window.url is None
        or (query := _followup_query(unit)) is None
    ):
        return outcome, 0.0
    followup_started = time.perf_counter()
    highlights = await fetcher.highlights(pc.window.url, query)
    pc.window = _append_highlights(pc.window, highlights or [])
    pc.window = pc.window.model_copy(
        update={
            "latency_ms": pc.window.latency_ms
            + (time.perf_counter() - followup_started) * 1000
        }
    )
    if not highlights:
        return outcome, 0.0
    judged, latencies = await judge_with_latencies(backend, [pc])
    result = judged.get(pc.case.case_id, "no result for this case")
    if isinstance(result, str):
        raise HTTPException(status_code=502, detail=f"Judge backend failed: {result}")
    return result, latencies.get(pc.case.case_id, 0.0)


async def _judge_unit(
    req: AuditDiffRequest,
    unit: EditUnit,
    changed_refs: list[str] | None,
    diff_scan: ScanResult,
    fetcher: SourceFetcher,
    backend: AsyncJudge | None,
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
                raise JudgeUnavailableError(stage0.latency_ms)
            ref_scans: list[ScanResult] = []
            pc.window = await _window_for(case, fetcher, ref_scans)
            pc.ref_scan = _worst_scan(ref_scans)
            pc.stealth_ms = sum(s.scan_latency_ms for s in ref_scans)
            judged, latencies = await judge_with_latencies(backend, [pc])
            stage2_ms = latencies.get(case.case_id, 0.0)
            outcome = judged.get(case.case_id, "no result for this case")
            if isinstance(outcome, str):
                raise HTTPException(
                    status_code=502, detail=f"Judge backend failed: {outcome}"
                )
            outcome, followup_ms = await _maybe_followup_judge(
                fetcher, backend, pc, unit, outcome
            )
            stage2_ms += followup_ms
            judged[case.case_id] = outcome
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


async def audit_diff_logic(
    req: AuditDiffRequest,
    process_fetcher: SourceFetcher,
    backend: AsyncJudge | None,
    auditor_provider: AuditorProvider,
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
    fetcher = process_fetcher.for_request(
        max_calls=min(EXA_CALLS_PER_UNIT * len(units), MAX_REQUEST_EXA_CALLS)
    )
    unit_regions = _unit_regions(new_scan, units)
    refs_by_unit = {u.index: _unit_changed_refs(u) for u in units}
    # Edit-relative: render only refs the edit touched. Without wikitext the
    # changed refs are unknown, so fall back to ref_urls unless Stage 0 says the
    # unit is a typo/format-only change (nothing new to plant on a cited page).
    union_refs: list[str] = []
    for unit in units:
        unit_refs = refs_by_unit[unit.index]
        if unit_refs is None:
            clean = prefilter(unit.old_text, unit.new_text, req.lang_code).clean
            unit_refs = [] if clean else req.ref_urls
        for url in unit_refs:
            if url not in union_refs:
                union_refs.append(url)
    render_task = asyncio.create_task(
        render_ref_pages_in_temp_dir(union_refs, auditor_provider)
    )
    citation_wikitexts = _citation_wikitexts(units)
    citation_dates_task: asyncio.Task[CitationDateScan] | None = None
    citation_dates_started: asyncio.Future[float] | None = None
    if citation_wikitexts:
        citation_dates_started = asyncio.get_running_loop().create_future()
        citation_dates_task = asyncio.create_task(
            _scan_citation_dates(
                req.lang_code,
                req.page_title,
                citation_wikitexts,
                citation_dates_started,
            )
        )
        await citation_dates_started
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
        except JudgeUnavailableError as exc:
            await _cancel_all(unit_tasks)
            exc.stealth_status = diff_scan.stealth_status.value
            exc.finding_count = len(reportable_findings(diff_scan))
            exc.stealth_ms = stealth_ms
            raise
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
        # Scored only now: the units' Exa fetches have cached the judged text.
        render = summarize_render(await _await_render(render_task), fetcher.cached_text)
        if citation_dates_task is None:
            citation_dates = CitationDateScan(status="skipped")
        else:
            assert citation_dates_started is not None
            citation_dates = await _await_completed_citation_dates(
                citation_dates_task,
                citation_dates_started.result(),
            )
        unit_routes: list[Route] = [route(o.result) for o in outcomes]
        top_route = max(unit_routes, key=ROUTE_RANK.__getitem__)
        if render.escalate:
            top_route = "admin"
        elif partial and top_route == "none":
            top_route = "review"
        if citation_dates.findings and top_route == "none":
            top_route = "review"
        contributing = [o for o in outcomes if o.output.verdict in FLAGS] or [
            top_outcome
        ]
        stealth_statuses = [
            s for o in outcomes if (s := _stealth_status(o.pc)) is not None
        ]
        ref_findings = sum(
            len(reportable_findings(o.pc.ref_scan)) for o in outcomes if o.pc.ref_scan
        )
        ref_scan_ms = sum(o.pc.stealth_ms for o in outcomes)
        reasons = [
            reason_code(o.output, o.pc.case.old_text, o.pc.case.new_text)
            for o in outcomes
        ]
        top_reason = (
            "CITATION_DATE"
            if citation_dates.findings
            else reasons[outcomes.index(top_outcome)]
        )
        old_wikitext = req.old_wikitext or req.old_text
        new_wikitext = req.new_wikitext or req.new_text
        judge_inputs = [
            JudgeFlagInput(
                unit_index=o.unit.index,
                output=o.output,
                reason_code=reason,
                tier=_flag_tier(unit_route),
                old_text=o.pc.case.old_text,
                new_text=o.pc.case.new_text,
                old_wikitext=old_wikitext,
                new_wikitext=new_wikitext,
                citations=o.pc.case.changed_ref_urls or o.pc.case.ref_urls,
                evidence=(
                    [
                        FlagEvidence(
                            source="cited",
                            quote=o.pc.window.text,
                            url=o.pc.window.url,
                        )
                    ]
                    if o.pc.window is not None
                    else []
                ),
                window=o.pc.window,
            )
            for o, unit_route, reason in zip(
                outcomes, unit_routes, reasons, strict=True
            )
        ]
        stealth_inputs = [
            StealthFlagInput(
                finding=finding,
                tier=_stealth_flag_tier(diff_scan.stealth_status),
                side_text=new_wikitext,
                evidence_source="new",
            )
            for finding in reportable_findings(diff_scan)
        ]
        for outcome in outcomes:
            if outcome.pc.ref_scan is None:
                continue
            stealth_inputs.extend(
                StealthFlagInput(
                    finding=finding,
                    tier=_stealth_flag_tier(outcome.pc.ref_scan.stealth_status),
                    side_text=new_wikitext,
                    evidence_source="cited",
                    evidence_url=(
                        outcome.pc.window.url if outcome.pc.window is not None else None
                    ),
                )
                for finding in reportable_findings(outcome.pc.ref_scan)
            )
        response_flags = build_flags(
            judge_inputs,
            stealth_inputs,
            citation_dates.findings,
            render.findings,
            new_wikitext,
            union_refs or req.ref_urls,
        )
        return AuditDiffResponse(
            verdict=output.verdict,
            confidence=output.confidence,
            reason=top_reason,
            reason_text=REASON_TEXT[top_reason] if top_reason else None,
            flags=response_flags,
            flagged_spans=[
                span
                for o in contributing
                for span in _spans_with_offsets(
                    o.output,
                    new_scan,
                    req.new_text,
                    unit_regions.get(o.unit.index),
                    o.pc.case.new_text,
                    o.pc.case.old_text,
                )
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
                finding_count=len(reportable_findings(diff_scan)) + ref_findings,
            ),
            render=render,
            citation_dates=citation_dates,
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
                    reason=reason,
                )
                for o, r, reason in zip(outcomes, unit_routes, reasons, strict=True)
            ],
            partial=partial,
        )
    except BaseException:
        render_task.cancel()
        with contextlib.suppress(BaseException):
            await render_task
        if citation_dates_task is not None:
            citation_dates_task.cancel()
            with contextlib.suppress(BaseException):
                await citation_dates_task
        raise


@app.post("/api/v1/audit-diff", response_model=AuditDiffResponse)
async def audit_diff(
    req: AuditDiffRequest,
    process_fetcher: Annotated[SourceFetcher, Depends(get_fetcher)],
    backend: Annotated[AsyncJudge | None, Depends(get_judge_backend)],
    auditor_provider: Annotated[AuditorProvider, Depends(get_auditor_provider)],
) -> AuditDiffResponse:
    try:
        return await audit_diff_logic(req, process_fetcher, backend, auditor_provider)
    except JudgeUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Judge backend unavailable: set GEMINI_API_KEY to enable Stage 2. "
            "No verdict was produced.",
        ) from exc

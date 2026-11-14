"""Pipeline orchestration: Stage 0 -> Stage 1 -> batch files."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from palimpsest.backends.gemini import GeminiJudgeBackend
from palimpsest.judge import (
    PROMPT_VERSION,
    PROMPTS_DIR,
    FileExchangeBackend,
    PreparedCase,
)
from palimpsest.report import render_report
from palimpsest.schema import (
    AuditOutput,
    Case,
    CaseResult,
    ExpandDirection,
    SourceWindow,
    Verdict,
    dump_jsonl,
    load_cases,
)
from palimpsest.scoring import score
from palimpsest.sources import SourceFetcher, load_exa_api_key
from palimpsest.stage0 import changed_region_has_citation, prefilter, strip_wikitext
from palimpsest.stealth.models import ScanResult, StealthStatus
from palimpsest.stealth.scanner import scan, worst_status

STAGE1_CONCURRENCY: Final = 8
MAX_SOURCE_URLS: Final = 3
CACHE_DIR: Final = Path("cache/exa")


class Manifest(BaseModel):
    prompt_version: str
    models: list[str]
    case_files: list[str]


def _ref_scanner(
    ref_scans: list[ScanResult] | None,
) -> Callable[[str], str | None] | None:
    """Scan fetched page text; withhold pages flagged CRITICAL from windowing."""
    if ref_scans is None:
        return None

    def on_text(text: str) -> str | None:
        result = scan(text, "EXTERNAL_REF_PAGE")
        ref_scans.append(result)
        if result.stealth_status == StealthStatus.CRITICAL_AI_POISONING:
            return None
        return result.sanitized_human_text

    return on_text


def _worst_scan(scans: list[ScanResult]) -> ScanResult | None:
    if not scans:
        return None
    worst = worst_status(s.stealth_status for s in scans)
    return next(s for s in scans if s.stealth_status == worst)


def _sanitized(text: str) -> tuple[str, float]:
    result = scan(text, "WIKIPEDIA_DIFF")
    return result.sanitized_human_text, result.scan_latency_ms


async def _window_for(
    case: Case, fetcher: SourceFetcher, ref_scans: list[ScanResult] | None = None
) -> SourceWindow:
    if case.source_window is not None:
        return SourceWindow(
            url=None, status="fixed", text=case.source_window, latency_ms=0.0
        )
    urls = case.changed_ref_urls or case.ref_urls
    if case.changed_ref_urls is not None and not case.changed_ref_urls:
        has_changed_citation = (
            bool(case.ref_urls)
            and case.old_wikitext is not None
            and case.new_wikitext is not None
            and changed_region_has_citation(case.old_wikitext, case.new_wikitext)
        )
        if not has_changed_citation:
            return SourceWindow(url=None, status="uncited", text="", latency_ms=0.0)
    claim = strip_wikitext(case.new_text)
    best: tuple[SourceWindow, int] | None = None
    for url in urls[:MAX_SOURCE_URLS]:
        scored = await fetcher.window_scored(
            url, claim, on_text=_ref_scanner(ref_scans)
        )
        if scored[0].status == "ok" and (best is None or scored[1] > best[1]):
            best = scored
    if best is not None:
        return best[0]
    return SourceWindow(url=None, status="unavailable", text="", latency_ms=0.0)


async def prepare(
    cases_paths: list[Path],
    run_dir: Path,
    models: list[str],
    prompt_version: str = PROMPT_VERSION,
    batch_size: int = 10,
    backend: str = "file",
    gemini_backend: GeminiJudgeBackend | None = None,
) -> None:
    if not (PROMPTS_DIR / f"{prompt_version}.txt").is_file():
        raise SystemExit(f"unknown prompt version: {prompt_version}")
    if backend not in ("file", "gemini"):
        raise SystemExit(f"unknown backend: {backend}")
    if backend == "gemini" and gemini_backend is None:
        gemini_backend = GeminiJudgeBackend(prompt_version=prompt_version)
    cases: dict[str, Case] = {}
    for path in cases_paths:
        for case in load_cases(path):
            cases.setdefault(case.case_id, case)
    fetcher = SourceFetcher(load_exa_api_key(), CACHE_DIR)
    semaphore = asyncio.Semaphore(STAGE1_CONCURRENCY)

    async def prepare_one(case: Case) -> PreparedCase:
        diff_scan = scan(
            case.new_wikitext or case.new_text,
            "WIKIPEDIA_DIFF",
            old_text=case.old_wikitext or case.old_text,
        )
        old_text, old_ms = _sanitized(case.old_text)
        new_text, new_ms = _sanitized(case.new_text)
        stealth_ms = diff_scan.scan_latency_ms + old_ms + new_ms
        case = case.model_copy(update={"old_text": old_text, "new_text": new_text})
        stage0 = prefilter(case.old_text, case.new_text, case.lang)
        if stage0.clean:
            return PreparedCase(
                case=case,
                stage0=stage0,
                window=None,
                diff_scan=diff_scan,
                stealth_ms=stealth_ms,
            )
        ref_scans: list[ScanResult] = []
        async with semaphore:
            window = await _window_for(case, fetcher, ref_scans)
        return PreparedCase(
            case=case,
            stage0=stage0,
            window=window,
            diff_scan=diff_scan,
            ref_scan=_worst_scan(ref_scans),
            stealth_ms=stealth_ms + sum(s.scan_latency_ms for s in ref_scans),
        )

    prepared = list(await asyncio.gather(*(prepare_one(c) for c in cases.values())))
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_jsonl(run_dir / "prepared.jsonl", prepared)
    if gemini_backend is not None:
        models = [gemini_backend.model]
    manifest = Manifest(
        prompt_version=prompt_version,
        models=models,
        case_files=[str(p) for p in cases_paths],
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    if gemini_backend is not None:
        await _judge_with_gemini(gemini_backend, prepared, run_dir)
        batches: list[Path] = []
    else:
        batches = FileExchangeBackend().write_batches(
            prepared,
            run_dir,
            models,
            batch_size=batch_size,
            prompt_version=prompt_version,
        )
    print(f"Exa calls: {fetcher.calls}, cost ${fetcher.cost_dollars:.4f}")
    clean = sum(1 for pc in prepared if pc.stage0.clean)
    print(
        f"{len(prepared)} cases, {clean} stage-0 clean, "
        f"{len(batches)} batch files in {run_dir / 'batches'}"
    )


async def _judge_with_gemini(
    backend: GeminiJudgeBackend, prepared: list[PreparedCase], run_dir: Path
) -> None:
    """Judge inline and write results in the file-exchange format ingest reads."""
    judged = await backend.judge([pc for pc in prepared if not pc.stage0.clean])
    lines: list[str] = []
    for case_id, outcome in judged.items():
        row: dict[str, object] = {
            "case_id": case_id,
            "stage2_ms": backend.latencies_ms.get(case_id, 0.0),
        }
        if isinstance(outcome, str):
            row["error"] = outcome
        else:
            row["output"] = outcome.model_dump(mode="json")
        lines.append(json.dumps(row))
    path = run_dir / "results" / backend.model / "batch_001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _stage0_clean_output() -> AuditOutput:
    return AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )


def _scans(pc: PreparedCase) -> list[ScanResult]:
    return [s for s in (pc.diff_scan, pc.ref_scan) if s is not None]


def _stealth_status(pc: PreparedCase) -> str | None:
    scans = _scans(pc)
    if not scans:
        return None
    return worst_status(s.stealth_status for s in scans).value


def _stealth_vectors(pc: PreparedCase) -> list[str]:
    return sorted({f.vector_type.value for s in _scans(pc) for f in s.hidden_findings})


def _case_result(
    pc: PreparedCase,
    model: str,
    judged: dict[str, AuditOutput | str],
    prompt_version: str,
    stage2_ms: float = 0.0,
) -> CaseResult:
    window = pc.window
    base = {
        "case_id": pc.case.case_id,
        "model": model,
        "prompt_version": prompt_version,
        "stage0_ms": pc.stage0.latency_ms,
        "stage1_ms": window.latency_ms if window else 0.0,
        "source_status": window.status if window else "skipped",
        "stealth_status": _stealth_status(pc),
        "stealth_vectors": _stealth_vectors(pc),
        "stealth_ms": pc.stealth_ms,
        "stage2_ms": 0.0 if pc.stage0.clean else stage2_ms,
    }
    if pc.stage0.clean:
        return CaseResult(
            **base, stage_reached=0, output=_stage0_clean_output(), parse_error=None
        )
    outcome = judged.get(pc.case.case_id, "no result line for this case")
    if isinstance(outcome, str):
        return CaseResult(**base, stage_reached=1, output=None, parse_error=outcome)
    return CaseResult(**base, stage_reached=2, output=outcome, parse_error=None)


def ingest(run_dir: Path, compare_to: Path | None = None) -> None:
    prepared = [
        PreparedCase.model_validate_json(line)
        for line in (run_dir / "prepared.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    backend = FileExchangeBackend()
    results: dict[str, list[CaseResult]] = {}
    for model in manifest.models:
        judged = backend.read_results(run_dir, model)
        stage2_ms = backend.read_stage2_ms(run_dir, model)
        results[model] = [
            _case_result(
                pc,
                model,
                judged,
                manifest.prompt_version,
                stage2_ms.get(pc.case.case_id, 0.0),
            )
            for pc in prepared
        ]
    metrics = score(prepared, results)
    dump_jsonl(
        run_dir / "results.jsonl", [r for rows in results.values() for r in rows]
    )
    path = render_report(run_dir, prepared, results, metrics, compare_to)
    for model, m in metrics.items():
        print(
            f"{model}: recall={m.violation_recall:.0%} clean_flag={m.clean_flag_rate:.0%} "
            f"parse_err={m.parse_error_rate:.0%} pass={m.passes_bar}"
        )
    print(f"report: {path}")

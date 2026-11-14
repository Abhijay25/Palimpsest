"""Pipeline orchestration: Stage 0 -> Stage 1 -> batch files."""

import asyncio
from pathlib import Path
from typing import Final

from pydantic import BaseModel

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
from palimpsest.stage0 import prefilter, strip_wikitext

STAGE1_CONCURRENCY: Final = 8
MAX_SOURCE_URLS: Final = 3
CACHE_DIR: Final = Path("cache/exa")


class Manifest(BaseModel):
    prompt_version: str
    models: list[str]
    case_files: list[str]


async def _window_for(case: Case, fetcher: SourceFetcher) -> SourceWindow:
    if case.source_window is not None:
        return SourceWindow(
            url=None, status="fixed", text=case.source_window, latency_ms=0.0
        )
    if case.changed_ref_urls is not None and not case.changed_ref_urls:
        return SourceWindow(url=None, status="uncited", text="", latency_ms=0.0)
    urls = case.ref_urls if case.changed_ref_urls is None else case.changed_ref_urls
    claim = strip_wikitext(case.new_text)
    best: tuple[SourceWindow, int] | None = None
    for url in urls[:MAX_SOURCE_URLS]:
        scored = await fetcher.window_scored(url, claim)
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
) -> None:
    if not (PROMPTS_DIR / f"{prompt_version}.txt").is_file():
        raise SystemExit(f"unknown prompt version: {prompt_version}")
    cases: dict[str, Case] = {}
    for path in cases_paths:
        for case in load_cases(path):
            cases.setdefault(case.case_id, case)
    fetcher = SourceFetcher(load_exa_api_key(), CACHE_DIR)
    semaphore = asyncio.Semaphore(STAGE1_CONCURRENCY)

    async def prepare_one(case: Case) -> PreparedCase:
        stage0 = prefilter(case.old_text, case.new_text, case.lang)
        if stage0.clean:
            return PreparedCase(case=case, stage0=stage0, window=None)
        async with semaphore:
            window = await _window_for(case, fetcher)
        return PreparedCase(case=case, stage0=stage0, window=window)

    prepared = list(await asyncio.gather(*(prepare_one(c) for c in cases.values())))
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_jsonl(run_dir / "prepared.jsonl", prepared)
    manifest = Manifest(
        prompt_version=prompt_version,
        models=models,
        case_files=[str(p) for p in cases_paths],
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    batches = FileExchangeBackend().write_batches(
        prepared, run_dir, models, batch_size=batch_size, prompt_version=prompt_version
    )
    print(f"Exa calls: {fetcher.calls}, cost ${fetcher.cost_dollars:.4f}")
    clean = sum(1 for pc in prepared if pc.stage0.clean)
    print(
        f"{len(prepared)} cases, {clean} stage-0 clean, "
        f"{len(batches)} batch files in {run_dir / 'batches'}"
    )


def _stage0_clean_output() -> AuditOutput:
    return AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )


def _case_result(
    pc: PreparedCase,
    model: str,
    judged: dict[str, AuditOutput | str],
    prompt_version: str,
) -> CaseResult:
    window = pc.window
    base = {
        "case_id": pc.case.case_id,
        "model": model,
        "prompt_version": prompt_version,
        "stage0_ms": pc.stage0.latency_ms,
        "stage1_ms": window.latency_ms if window else 0.0,
        "source_status": window.status if window else "skipped",
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
        results[model] = [
            _case_result(pc, model, judged, manifest.prompt_version) for pc in prepared
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

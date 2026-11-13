"""Pipeline orchestration: Stage 0 -> Stage 1 -> batch files."""

import asyncio
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from palimpsest.judge import PROMPT_VERSION, FileExchangeBackend, PreparedCase
from palimpsest.schema import Case, SourceWindow, dump_jsonl, load_cases
from palimpsest.sources import SourceFetcher, load_exa_api_key
from palimpsest.stage0 import prefilter, strip_wikitext

STAGE1_CONCURRENCY: Final = 8
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
    claim = strip_wikitext(case.new_text)
    for url in case.ref_urls:
        window = await fetcher.window(url, claim)
        if window.status == "ok":
            return window
    return SourceWindow(url=None, status="unavailable", text="", latency_ms=0.0)


async def prepare(cases_paths: list[Path], run_dir: Path, models: list[str]) -> None:
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
        prompt_version=PROMPT_VERSION,
        models=models,
        case_files=[str(p) for p in cases_paths],
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    batches = FileExchangeBackend().write_batches(prepared, run_dir, models)
    clean = sum(1 for pc in prepared if pc.stage0.clean)
    print(
        f"{len(prepared)} cases, {clean} stage-0 clean, "
        f"{len(batches)} batch files in {run_dir / 'batches'}"
    )

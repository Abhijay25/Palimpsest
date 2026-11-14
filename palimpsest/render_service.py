"""Pillar 3 render scan of cited pages, run concurrently with the judge."""

import asyncio
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from palimpsest.stealth.models import HiddenFinding
from palimpsest.stealth.pillar3 import render_findings
from palimpsest.stealth.render import PageRenderer, RenderAudit
from palimpsest.stealth.sanitizer import looks_like_instruction

logger = logging.getLogger(__name__)

RENDER_ENV: str = "PALIMPSEST_RENDER"
DEFAULT_MAX_PAGES = 3
DEFAULT_TIMEOUT_S = 15.0


class RenderSummary(BaseModel):
    status: Literal["ok", "partial", "unavailable", "skipped"]
    pages_rendered: int = 0
    pages_failed: int = 0
    findings: list[HiddenFinding] = []
    escalate: bool = False
    latency_ms: float = 0.0


class PageAuditor(Protocol):
    async def audit_url(self, url: str, out_dir: Path) -> RenderAudit: ...


AuditorProvider = Callable[[], Awaitable[PageAuditor | None]]


async def _audit_one(
    url: str,
    auditor: PageAuditor,
    out_dir: Path,
    timeout_s: float,
) -> RenderAudit | None:
    """Render one page; any blocked URL, timeout or browser error yields None."""
    try:
        return await asyncio.wait_for(auditor.audit_url(url, out_dir), timeout_s)
    except Exception as exc:  # noqa: BLE001 - RenderBlockedError, timeouts, Playwright errors
        logger.info("render scan failed for %s: %s", url, type(exc).__name__)
        return None


async def scan_ref_pages(
    urls: list[str],
    auditor: PageAuditor | None,
    judged_text_for: Callable[[str], str | None],
    out_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RenderSummary:
    started = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000

    if not urls:
        return RenderSummary(status="skipped", latency_ms=elapsed_ms())
    if auditor is None:
        return RenderSummary(status="unavailable", latency_ms=elapsed_ms())
    chosen = urls[:max_pages]
    audits = await asyncio.gather(
        *(
            _audit_one(url, auditor, out_dir / str(i), timeout_s)
            for i, url in enumerate(chosen)
        )
    )
    findings: list[HiddenFinding] = []
    rendered = 0
    for url, audit in zip(chosen, audits, strict=True):
        if audit is None:
            continue
        rendered += 1
        # Read lazily: the judge path's Exa fetch has populated the cache by now.
        findings.extend(render_findings(audit, judged_text_for(url)))
    failed = len(chosen) - rendered
    status: Literal["ok", "partial", "unavailable"] = (
        "unavailable" if rendered == 0 else "partial" if failed else "ok"
    )
    return RenderSummary(
        status=status,
        pages_rendered=rendered,
        pages_failed=failed,
        findings=findings,
        escalate=any(looks_like_instruction(f.decoded_hidden_text) for f in findings),
        latency_ms=elapsed_ms(),
    )


async def scan_ref_pages_in_temp_dir(
    urls: list[str],
    provider: AuditorProvider,
    judged_text_for: Callable[[str], str | None],
) -> RenderSummary:
    """Per-request entry point: starts the shared renderer only if there is work."""
    if not urls:
        return await scan_ref_pages(urls, None, judged_text_for, Path())
    auditor = await provider()
    with tempfile.TemporaryDirectory(prefix="palimpsest-render-") as tmp:
        return await scan_ref_pages(urls, auditor, judged_text_for, Path(tmp))


_renderer: PageRenderer | None = None
_renderer_failed = False
_renderer_lock: asyncio.Lock | None = None


async def shared_auditor() -> PageAuditor | None:
    """Lazily started process-wide renderer; None when disabled or unlaunchable."""
    global _renderer, _renderer_failed, _renderer_lock
    if os.environ.get(RENDER_ENV) == "0" or _renderer_failed:
        return None
    if _renderer is not None:
        return _renderer
    if _renderer_lock is None:
        _renderer_lock = asyncio.Lock()
    async with _renderer_lock:
        if _renderer is not None:
            return _renderer
        if _renderer_failed:
            return None
        try:
            _renderer = await PageRenderer(screenshots="none").__aenter__()
        except Exception:  # missing chromium or launch failure
            _renderer_failed = True
            logger.exception("render scan disabled: could not start chromium")
            return None
        return _renderer


async def close_shared_auditor() -> None:
    global _renderer, _renderer_lock
    renderer, _renderer, _renderer_lock = _renderer, None, None
    if renderer is not None:
        await renderer.__aexit__(None, None, None)

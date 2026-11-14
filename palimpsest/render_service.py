"""Pillar 3 render scan of cited pages, run concurrently with the judge."""

import asyncio
import contextlib
import logging
import os
import tempfile
import time
import weakref
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
    # Rendered pages whose tiles could not be scrolled, so occlusion went unchecked.
    pages_scroll_locked: int = 0
    findings: list[HiddenFinding] = []
    escalate: bool = False
    latency_ms: float = 0.0


class RenderedPages(BaseModel):
    """Raw render results; scoring against the judged text happens later."""

    status: Literal["ok", "partial", "unavailable", "skipped"]
    audits: list[RenderAudit] = []
    failed: int = 0
    latency_ms: float = 0.0


class PageAuditor(Protocol):
    async def audit_url(self, url: str, out_dir: Path) -> RenderAudit: ...


AuditorProvider = Callable[[], Awaitable[PageAuditor | None]]

# Process-wide cap on concurrent page audits (one shared browser).
RENDER_CONCURRENCY = 4
# After a failed launch, wait this long before trying to start chromium again.
LAUNCH_RETRY_BACKOFF_S = 60.0
_monotonic: Callable[[], float] = time.monotonic
_render_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _render_semaphore() -> asyncio.Semaphore:
    """The audit semaphore of the running loop (a semaphore must not cross loops)."""
    loop = asyncio.get_running_loop()
    semaphore = _render_semaphores.get(loop)
    if semaphore is None:
        semaphore = _render_semaphores[loop] = asyncio.Semaphore(RENDER_CONCURRENCY)
    return semaphore


async def _audit_one(
    url: str,
    auditor: PageAuditor,
    out_dir: Path,
    timeout_s: float,
) -> RenderAudit | None:
    """Render one page; any blocked URL, timeout or browser error yields None."""
    try:
        async with _render_semaphore():
            return await asyncio.wait_for(auditor.audit_url(url, out_dir), timeout_s)
    except Exception as exc:  # noqa: BLE001 - RenderBlockedError, timeouts, Playwright errors
        logger.info("render scan failed for %s: %s", url, type(exc).__name__)
        return None


async def render_ref_pages(
    urls: list[str],
    auditor: PageAuditor | None,
    out_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RenderedPages:
    """Render only; findings are computed later by summarize_render."""
    started = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000

    if not urls:
        return RenderedPages(status="skipped", latency_ms=elapsed_ms())
    if auditor is None:
        return RenderedPages(status="unavailable", latency_ms=elapsed_ms())
    chosen = urls[:max_pages]
    results = await asyncio.gather(
        *(
            _audit_one(url, auditor, out_dir / str(i), timeout_s)
            for i, url in enumerate(chosen)
        )
    )
    audits = [a for a in results if a is not None]
    failed = len(chosen) - len(audits)
    return RenderedPages(
        status="unavailable" if not audits else "partial" if failed else "ok",
        audits=audits,
        failed=failed,
        latency_ms=elapsed_ms(),
    )


def summarize_render(
    rendered: RenderedPages, judged_text_for: Callable[[str], str | None]
) -> RenderSummary:
    """Score rendered pages against the judged text; call once the Exa text is cached."""
    if rendered.status in ("skipped", "unavailable") and not rendered.audits:
        return RenderSummary(
            status=rendered.status,
            pages_failed=rendered.failed,
            latency_ms=rendered.latency_ms,
        )
    findings: list[HiddenFinding] = []
    scroll_locked = 0
    for audit in rendered.audits:
        scroll_locked += any(t.scroll_locked for t in audit.tiles)
        findings.extend(
            render_findings(audit, judged_text_for(audit.url) if audit.url else None)
        )
    status: Literal["ok", "partial"] = (
        "partial" if rendered.failed or scroll_locked else "ok"
    )
    return RenderSummary(
        status=status,
        pages_rendered=len(rendered.audits),
        pages_failed=rendered.failed,
        pages_scroll_locked=scroll_locked,
        findings=findings,
        escalate=any(looks_like_instruction(f.decoded_hidden_text) for f in findings),
        latency_ms=rendered.latency_ms,
    )


async def scan_ref_pages(
    urls: list[str],
    auditor: PageAuditor | None,
    judged_text_for: Callable[[str], str | None],
    out_dir: Path,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RenderSummary:
    rendered = await render_ref_pages(urls, auditor, out_dir, max_pages, timeout_s)
    return summarize_render(rendered, judged_text_for)


async def render_ref_pages_in_temp_dir(
    urls: list[str],
    provider: AuditorProvider,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RenderedPages:
    """Per-request entry point: starts the shared renderer only if there is work.

    The browser launch counts against the same timeout as the page audits.
    """
    if not urls:
        return await render_ref_pages(urls, None, Path())
    started = time.perf_counter()
    # Shielded: a timed-out caller must not abort a launch other requests wait on.
    launch = asyncio.ensure_future(provider())
    try:
        auditor = await asyncio.wait_for(asyncio.shield(launch), timeout_s)
    except Exception as exc:  # noqa: BLE001 - launch timeout or provider failure
        logger.info("render launch failed: %s", type(exc).__name__)
        launch.add_done_callback(lambda f: f.cancelled() or f.exception())
        return RenderedPages(
            status="unavailable", latency_ms=(time.perf_counter() - started) * 1000
        )
    with tempfile.TemporaryDirectory(prefix="palimpsest-render-") as tmp:
        return await render_ref_pages(urls, auditor, Path(tmp), timeout_s=timeout_s)


_renderer: PageRenderer | None = None
_launch_failed_at: float | None = None
_renderer_lock: asyncio.Lock | None = None


async def shared_auditor() -> PageAuditor | None:
    """Lazily started process-wide renderer; None when disabled or unlaunchable.

    A disconnected browser is relaunched on a later request; a failed launch is
    retried no more often than every LAUNCH_RETRY_BACKOFF_S.
    """
    global _renderer, _launch_failed_at, _renderer_lock
    if os.environ.get(RENDER_ENV) == "0":
        return None
    if _renderer is not None and _renderer.is_connected():
        return _renderer
    if _renderer_lock is None:
        _renderer_lock = asyncio.Lock()
    async with _renderer_lock:
        if _renderer is not None and _renderer.is_connected():
            return _renderer
        if _renderer is not None:
            dead, _renderer = _renderer, None
            with contextlib.suppress(Exception):
                await dead.__aexit__(None, None, None)
        if (
            _launch_failed_at is not None
            and _monotonic() - _launch_failed_at < LAUNCH_RETRY_BACKOFF_S
        ):
            return None
        try:
            _renderer = await PageRenderer(screenshots="none").__aenter__()
        except Exception:  # missing chromium or launch failure
            _launch_failed_at = _monotonic()
            logger.exception("render scan unavailable: could not start chromium")
            return None
        _launch_failed_at = None
        return _renderer


async def close_shared_auditor() -> None:
    global _renderer, _renderer_lock, _launch_failed_at
    renderer, _renderer, _renderer_lock = _renderer, None, None
    _launch_failed_at = None
    if renderer is not None:
        await renderer.__aexit__(None, None, None)

import asyncio
import ipaddress
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import TracebackType
from typing import Literal, Self
from urllib.parse import urlsplit

from playwright.async_api import (
    Browser,
    Playwright,
    Request,
    Route,
    async_playwright,
)
from pydantic import BaseModel, Field

HiddenReason = Literal[
    "display_none",
    "visibility_hidden",
    "transparent",
    "low_contrast",
    "tiny_font",
    "offscreen",
    "zero_size",
    "clipped",
    "occluded",
]

Rect = tuple[float, float, float, float]

VIEWPORT = (1280, 800)
TILE_OVERLAP_PX = 64
MAX_TILES = 12
SCROLL_TOLERANCE_PX = 2
# Read scrollY two frames later so scroll-reset listeners have run.
_SCROLL_Y_AFTER_FRAMES_JS = (
    "() => new Promise(r => requestAnimationFrame(() => "
    "requestAnimationFrame(() => r(Math.round(window.scrollY)))))"
)
NAV_TIMEOUT_MS = 10000
SETTLE_MS = 500


class HiddenTextNode(BaseModel):
    text: str
    reason: HiddenReason
    rect: Rect


class ImageRegion(BaseModel):
    kind: Literal["img", "svg", "canvas", "background"]
    rect: Rect
    alt: str


# An image smaller than this cannot carry a readable headline or quote.
MIN_TEXT_IMAGE_W = 120
MIN_TEXT_IMAGE_H = 60
# "none": deterministic checks only (no PNGs); "images": only tiles that overlap a
# text-capable image (what the vision layer reads); "all": every tile.
Screenshots = Literal["none", "images", "all"]


def text_capable(region: ImageRegion) -> bool:
    return region.rect[2] >= MIN_TEXT_IMAGE_W and region.rect[3] >= MIN_TEXT_IMAGE_H


def overlaps_text_image(images: list[ImageRegion], y_start: int, y_end: int) -> bool:
    return any(
        text_capable(r) and r.rect[1] < y_end and r.rect[1] + r.rect[3] > y_start
        for r in images
    )


class RenderedTile(BaseModel):
    index: int
    y_start: int
    y_end: int
    png_path: str
    visible_text: str
    # The page refused to scroll (e.g. a consent dialog locks the body), so the
    # tile was captured from the full-page layout and occlusion was not checked.
    scroll_locked: bool = False


class RenderAudit(BaseModel):
    url: str | None
    scraper_text: str
    human_text: str
    hidden_nodes: list[HiddenTextNode]
    image_regions: list[ImageRegion]
    tiles: list[RenderedTile]
    page_height: int
    truncated: bool
    blocked_requests: int
    render_ms: float


_RouteHandler = Callable[[Route, Request], Awaitable[None]]
_Counter = Callable[[], int]


class RenderBlockedError(ValueError):
    pass


class _RawNode(BaseModel):
    text: str
    parent: int
    reason: HiddenReason | None
    rect: Rect


class _RawCollect(BaseModel):
    nodes: list[_RawNode]
    images: list[ImageRegion]
    scroll_height: int


class _RawOcclusion(BaseModel):
    occluded: list[int] = Field(default_factory=list)


_COLLECT_JS = r"""
() => {
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
  const body = document.body;
  const root = document.documentElement;
  const scrollW = Math.max(root.scrollWidth, body ? body.scrollWidth : 0);
  const scrollH = Math.max(root.scrollHeight, body ? body.scrollHeight : 0);
  const sx = window.scrollX, sy = window.scrollY;
  window.__pal = { ranges: [], parents: new Map() };
  const out = { nodes: [], images: [], scroll_height: scrollH };
  if (!body) return out;

  const parseColor = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(parseFloat);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    return s === "transparent" ? { r: 0, g: 0, b: 0, a: 0 } : { r: 0, g: 0, b: 0, a: 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const toPx = (v, ref) => v.endsWith("%") ? parseFloat(v) / 100 * ref : parseFloat(v);

  const clipCollapsed = (el, cs, tr) => {
    const r = el.getBoundingClientRect();
    if (cs.clip && cs.clip.startsWith("rect(") && /^(absolute|fixed)$/.test(cs.position)) {
      const v = cs.clip.slice(5, -1).split(/[ ,]+/).filter(Boolean);
      if (v.length === 4) {
        const [t, rt, b, l] = v.map((x, i) => x === "auto" ? (i % 2 ? r.width : 0) : parseFloat(x));
        if (rt <= l || b <= t) return true;
        const c = { left: r.left + l, right: r.left + rt, top: r.top + t, bottom: r.top + b };
        if (tr.right <= c.left || tr.left >= c.right || tr.bottom <= c.top || tr.top >= c.bottom) return true;
      }
    }
    const cp = cs.clipPath || "";
    let m = cp.match(/^inset\(([^)]*)\)/);
    if (m) {
      const v = m[1].split(/\s+round\s+/)[0].trim().split(/\s+/);
      const t = toPx(v[0], r.height);
      const rt = toPx(v[1] ?? v[0], r.width);
      const b = toPx(v[2] ?? v[0], r.height);
      const l = toPx(v[3] ?? v[1] ?? v[0], r.width);
      if (t + b >= r.height || l + rt >= r.width) return true;
    }
    m = cp.match(/^circle\(\s*(0(?:px|%)?)[\s)]/);
    if (m) return true;
    return false;
  };

  const classify = (node, el) => {
    const chain = [];
    for (let e = el; e && e !== root; e = e.parentElement) chain.push(e);
    chain.push(root);
    const styles = chain.map((e) => getComputedStyle(e));
    const rects = Array.from(((r) => { r.selectNodeContents(node); return r; })(document.createRange()).getClientRects());
    const docRects = rects.map((r) => ({ left: r.left + sx, right: r.right + sx, top: r.top + sy, bottom: r.bottom + sy }));
    let union = [0, 0, 0, 0];
    let u = null;
    if (docRects.length) {
      u = { left: Math.min(...docRects.map((r) => r.left)), top: Math.min(...docRects.map((r) => r.top)),
            right: Math.max(...docRects.map((r) => r.right)), bottom: Math.max(...docRects.map((r) => r.bottom)) };
      union = [u.left, u.top, u.right - u.left, u.bottom - u.top];
    }
    const cs = styles[0];
    if (styles.some((s) => s.display === "none")) return ["display_none", union];
    if (cs.visibility === "hidden" || cs.visibility === "collapse") return ["visibility_hidden", union];
    const opacity = styles.reduce((p, s) => p * parseFloat(s.opacity), 1);
    const fg = parseColor(cs.color);
    if (opacity < 0.05 || fg.a < 0.05) return ["transparent", union];
    if (parseFloat(cs.fontSize) < 4) return ["tiny_font", union];
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    let unknownBg = false;
    for (const s of styles) {
      if (s.backgroundImage !== "none") { unknownBg = true; break; }
      const c = parseColor(s.backgroundColor);
      if (c.a > 0) { bg = over(c, bg); if (c.a >= 1) break; }
    }
    if (!unknownBg) {
      const a = lum(over(fg, bg)), b = lum(bg);
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      if (ratio < 1.5) return ["low_contrast", union];
    }
    if (!u) return ["zero_size", union];
    if (docRects.every((r) => r.right < 0 || r.bottom < 0 || r.left >= scrollW || r.top >= scrollH)) return ["offscreen", union];
    if (u.right - u.left < 2 || u.bottom - u.top < 2) return ["zero_size", union];
    const tr = { left: u.left - sx, right: u.right - sx, top: u.top - sy, bottom: u.bottom - sy };
    for (let i = 0; i < chain.length; i++) {
      const e = chain[i], s = styles[i];
      if (e === body || e === root) continue;
      if (clipCollapsed(e, s, tr)) return ["clipped", union];
      if (/^(hidden|clip)$/.test(s.overflowX) || /^(hidden|clip)$/.test(s.overflowY)) {
        const r = e.getBoundingClientRect();
        if (tr.right <= r.left || tr.left >= r.right || tr.bottom <= r.top || tr.top >= r.bottom) return ["clipped", union];
      }
    }
    return [null, union];
  };

  const parentIds = new Map();
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      if (!/\S/.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
      for (let e = n.parentElement; e; e = e.parentElement) if (SKIP.has(e.tagName)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    } });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!parentIds.has(el)) parentIds.set(el, parentIds.size);
    const [reason, rect] = classify(n, el);
    const range = document.createRange();
    range.selectNodeContents(n);
    window.__pal.ranges.push({ range, el });
    out.nodes.push({ text: n.nodeValue, parent: parentIds.get(el), reason, rect });
  }

  for (const el of document.querySelectorAll("body, body *")) {
    const tag = (el.tagName || "").toLowerCase();
    const cs = getComputedStyle(el);
    let kind = null;
    if (tag === "img" || tag === "svg" || tag === "canvas") kind = tag;
    else if (cs.backgroundImage !== "none") kind = "background";
    if (!kind) continue;
    if (cs.visibility !== "visible" || el.getClientRects().length === 0) continue;
    let op = 1;
    for (let e = el; e; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
    if (op < 0.05) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) continue;
    const alt = (tag === "img" ? el.getAttribute("alt") : null) || el.getAttribute("aria-label") || "";
    out.images.push({ kind, rect: [r.left + sx, r.top + sy, r.width, r.height], alt });
  }
  return out;
}
"""

_OCCLUSION_JS = r"""
(candidates) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const occluded = [];
  const fixedOrSticky = (e) => {
    for (; e; e = e.parentElement) {
      const p = getComputedStyle(e).position;
      if (p === "fixed" || p === "sticky") return true;
    }
    return false;
  };
  for (const i of candidates) {
    const { range, el } = window.__pal.ranges[i];
    const r = range.getClientRects()[0];
    if (!r) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= vw || cy >= vh) continue;
    const hit = document.elementFromPoint(cx, cy);
    if (!hit) continue;
    if (hit === el || el.contains(hit) || hit.contains(el)) continue;
    if (fixedOrSticky(hit)) continue;
    occluded.push(i);
  }
  return { occluded };
}
"""


async def check_public_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to public addresses."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    try:
        return _is_public_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port or (443 if parts.scheme == "https" else 80)
        )
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            if not _is_public_ip(ipaddress.ip_address(str(info[4][0]).split("%")[0])):
                return False
        except ValueError:
            return False
    return True


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _join(nodes: list[_RawNode]) -> str:
    parts: list[str] = []
    prev_parent: int | None = None
    for node in nodes:
        if prev_parent is not None and node.parent != prev_parent:
            parts.append(" ")
        parts.append(node.text)
        prev_parent = node.parent
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _union(a: Rect, b: Rect) -> Rect:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _merge(nodes: list[_RawNode]) -> list[_RawNode]:
    merged: list[_RawNode] = []
    for node in nodes:
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.parent == node.parent
            and last.reason == node.reason
        ):
            merged[-1] = _RawNode(
                text=last.text + node.text,
                parent=last.parent,
                reason=last.reason,
                rect=_union(last.rect, node.rect),
            )
        else:
            merged.append(node)
    return merged


def _tile_starts(page_height: int) -> tuple[list[int], bool]:
    viewport_h = VIEWPORT[1]
    step = viewport_h - TILE_OVERLAP_PX
    starts = [0]
    while starts[-1] + viewport_h < page_height:
        if len(starts) >= MAX_TILES:
            return starts, True
        nxt = starts[-1] + step
        if nxt + viewport_h >= page_height:
            nxt = page_height - viewport_h
        starts.append(nxt)
    return starts, False


def _resolve_chromium() -> str:
    path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    if not path:
        raise RuntimeError(
            "No chromium found: set CHROMIUM_PATH or put chromium on PATH"
        )
    return path


class PageRenderer:
    def __init__(self, screenshots: Screenshots = "all") -> None:
        self._screenshots: Screenshots = screenshots
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            executable_path=_resolve_chromium(), args=["--no-sandbox"], headless=True
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = self._playwright = None

    async def audit_html(self, html: str, out_dir: Path) -> RenderAudit:
        start = time.perf_counter()
        blocked = 0

        async def handler(route: Route, request: Request) -> None:
            nonlocal blocked
            if request.url.startswith(("data:", "about:")):
                await route.continue_()
                return
            blocked += 1
            await route.abort()

        return await self._audit(None, html, out_dir, handler, lambda: blocked, start)

    async def audit_url(self, url: str, out_dir: Path) -> RenderAudit:
        start = time.perf_counter()
        if not await check_public_url(url):
            raise RenderBlockedError(f"Refusing non-public or non-http(s) URL: {url}")
        blocked = 0
        verdicts: dict[str, bool] = {}

        async def handler(route: Route, request: Request) -> None:
            nonlocal blocked
            req_url = request.url
            if req_url.startswith(("data:", "about:")):
                await route.continue_()
                return
            host = urlsplit(req_url).hostname or ""
            key = f"{urlsplit(req_url).scheme}://{host}"
            if key not in verdicts:
                verdicts[key] = await check_public_url(req_url)
            if verdicts[key]:
                await route.continue_()
            else:
                blocked += 1
                await route.abort()

        return await self._audit(url, None, out_dir, handler, lambda: blocked, start)

    async def _audit(
        self,
        url: str | None,
        html: str | None,
        out_dir: Path,
        handler: _RouteHandler,
        blocked_count: _Counter,
        start: float,
    ) -> RenderAudit:
        if self._browser is None:
            raise RuntimeError("PageRenderer must be used as an async context manager")
        out_dir.mkdir(parents=True, exist_ok=True)
        context = await self._browser.new_context(
            java_script_enabled=True,
            accept_downloads=False,
            viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
        )
        try:
            await context.route("**/*", handler)
            page = await context.new_page()
            if url is not None:
                await page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
                if not await check_public_url(page.url):
                    raise RenderBlockedError(
                        f"Navigation ended on non-public URL: {page.url}"
                    )
                await page.wait_for_timeout(SETTLE_MS)
            else:
                assert html is not None
                await page.set_content(html, wait_until="load", timeout=NAV_TIMEOUT_MS)
            raw = _RawCollect.model_validate(await page.evaluate(_COLLECT_JS))
            page_height = raw.scroll_height
            starts, truncated = _tile_starts(page_height)
            png_paths: list[Path | None] = []
            locked: set[int] = set()

            async def capture_from_layout(png: Path, y_start: int) -> None:
                await page.screenshot(
                    path=str(png),
                    full_page=True,
                    clip={
                        "x": 0,
                        "y": y_start,
                        "width": VIEWPORT[0],
                        "height": min(VIEWPORT[1], page_height - y_start),
                    },
                )

            def moved(scrolled: object, y_start: int) -> bool:
                return abs(int(str(scrolled)) - y_start) > SCROLL_TOLERANCE_PX

            for index, y_start in enumerate(starts):
                want_png = self._screenshots == "all" or (
                    self._screenshots == "images"
                    and overlaps_text_image(raw.images, y_start, y_start + VIEWPORT[1])
                )
                png = out_dir / f"tile_{index:02d}.png"
                png_paths.append(png if want_png else None)
                await page.evaluate(
                    "y => window.scrollTo({top: y, left: 0, behavior: 'instant'})",
                    y_start,
                )
                if moved(await page.evaluate(_SCROLL_Y_AFTER_FRAMES_JS), y_start):
                    locked.add(index)
                    if want_png:
                        await capture_from_layout(png, y_start)
                    continue
                candidates = [i for i, n in enumerate(raw.nodes) if n.reason is None]
                occ = _RawOcclusion.model_validate(
                    await page.evaluate(_OCCLUSION_JS, candidates)
                )
                for i in occ.occluded:
                    raw.nodes[i].reason = "occluded"
                if not want_png:
                    continue
                await page.screenshot(path=str(png))
                # A late scroll reset can land after the frames waited above.
                if moved(
                    await page.evaluate("() => Math.round(window.scrollY)"), y_start
                ):
                    locked.add(index)
                    await capture_from_layout(png, y_start)
            await page.evaluate("() => window.scrollTo(0, 0)")
        finally:
            await context.close()

        merged = _merge(raw.nodes)
        visible = [n for n in raw.nodes if n.reason is None]
        visible_merged = [n for n in merged if n.reason is None]
        tiles: list[RenderedTile] = []
        for index, y_start in enumerate(starts):
            y_end = min(y_start + VIEWPORT[1], page_height)
            in_tile = [
                n
                for n in visible_merged
                if n.rect[1] < y_end and n.rect[1] + n.rect[3] >= y_start
            ]
            tiles.append(
                RenderedTile(
                    index=index,
                    y_start=y_start,
                    y_end=y_end,
                    png_path=str(png_paths[index]) if png_paths[index] else "",
                    visible_text=_join(in_tile),
                    scroll_locked=index in locked,
                )
            )
        return RenderAudit(
            url=url,
            scraper_text=_join(raw.nodes),
            human_text=_join(visible),
            hidden_nodes=[
                HiddenTextNode(
                    text=re.sub(r"\s+", " ", n.text).strip(),
                    reason=n.reason,
                    rect=n.rect,
                )
                for n in merged
                if n.reason is not None
            ],
            image_regions=raw.images,
            tiles=tiles,
            page_height=page_height,
            truncated=truncated,
            blocked_requests=blocked_count(),
            render_ms=(time.perf_counter() - start) * 1000,
        )

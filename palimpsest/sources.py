"""Stage 1: Exa-backed citation source windows with a JSON-file cache."""

import asyncio
import datetime
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Final, Literal, TypeVar, cast

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from palimpsest.schema import SourceWindow

EXA_CONTENTS_URL: Final = "https://api.exa.ai/contents"
REQUEST_TIMEOUT_S: Final = 10.0
MIN_TEXT_CHARS: Final = 200
# A window shorter than this, or sharing fewer claim tokens than MIN_OVERLAP,
# is a stub or off-topic page and is treated as unavailable (r04 finding).
MIN_WINDOW_CHARS: Final = 150
MIN_OVERLAP: Final = 2
MAX_WINDOW_CHARS: Final = 4_000
DEFAULT_MAX_EXA_CALLS: Final = 400
DEFAULT_DAILY_MAX_EXA_CALLS: Final = 2000
REQUEST_MAX_EXA_CALLS: Final = 3
# Failed or stub fetches are not retried for this long (saves Exa calls and latency).
NEGATIVE_CACHE_TTL_S: Final = 6 * 3600
_SENTENCE_SPLIT: Final = re.compile(r"(?<=[.!?])\s+")
_TOKEN: Final = re.compile(r"\w+")
_HEADING: Final = re.compile(r"^#{1,6}\s")


class _CachedText(BaseModel):
    text: str
    # Set on a negative entry: the fetch ran and failed or returned a stub.
    failed_at: float | None = None


class _FetchOutcome(BaseModel):
    """Result of one Exa call; classification travels with the result, not the instance."""

    text: str | None = None
    # A successful HTTP 200 whose body had no results or only a stub: retrying
    # soon will not help. Everything else (transport errors, 4xx/5xx) is transient.
    permanent_failure: bool = False


class _ExaResult(BaseModel):
    text: str | None = None
    highlights: list[str] = []


class _ExaStatus(BaseModel):
    status: str | None = None
    error: str | None = None


class _ExaCost(BaseModel):
    total: float = 0.0


class _ExaResponse(BaseModel):
    results: list[_ExaResult] = []
    statuses: list[_ExaStatus] = []
    costDollars: _ExaCost | None = None


class _HighlightsOutcome(BaseModel):
    highlights: list[str] = []
    permanent_failure: bool = False


_T = TypeVar("_T")


def load_exa_api_key() -> str | None:
    """Read EXA_API_KEY from .env / environment; empty string counts as missing."""
    load_dotenv()
    return os.environ.get("EXA_API_KEY") or None


def _daily_max_exa_calls() -> int:
    """EXA_DAILY_MAX_CALLS from the environment; unset or invalid falls back to the default."""
    try:
        return int(os.environ.get("EXA_DAILY_MAX_CALLS", DEFAULT_DAILY_MAX_EXA_CALLS))
    except ValueError:
        return DEFAULT_DAILY_MAX_EXA_CALLS


class DailyCallCap:
    """Process-wide Exa call cap that resets at UTC midnight."""

    def __init__(
        self,
        max_calls: int | None = None,
        today: Callable[[], datetime.date] = lambda: datetime.datetime.now(
            datetime.UTC
        ).date(),
    ) -> None:
        self._max_calls = _daily_max_exa_calls() if max_calls is None else max_calls
        self._today = today
        self._day = today()
        self._count = 0

    def try_acquire(self) -> bool:
        today = self._today()
        if today != self._day:
            self._day = today
            self._count = 0
        if self._count >= self._max_calls:
            return False
        self._count += 1
        return True


def _max_exa_calls() -> int:
    """EXA_MAX_CALLS from the environment; unset or invalid falls back to the default."""
    try:
        return int(os.environ.get("EXA_MAX_CALLS", DEFAULT_MAX_EXA_CALLS))
    except ValueError:
        return DEFAULT_MAX_EXA_CALLS


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def discourse_window_scored(text: str, claim: str, radius: int = 3) -> tuple[str, int]:
    """Best-overlap sentence +/- radius sentences with heading, plus the best overlap score."""
    sentences: list[str] = []
    heading_for: list[str | None] = []
    heading: str | None = None
    for line in text.splitlines():
        if _HEADING.match(line):
            heading = line.strip()
            continue
        for sentence in _SENTENCE_SPLIT.split(line.strip()):
            if sentence:
                sentences.append(sentence)
                heading_for.append(heading)
    if not sentences:
        return "", 0
    claim_tokens = _tokens(claim)
    best = max(
        range(len(sentences)), key=lambda i: len(claim_tokens & _tokens(sentences[i]))
    )
    start = max(0, best - radius)
    window = " ".join(sentences[start : best + radius + 1])
    heading_line = heading_for[start]
    score = len(claim_tokens & _tokens(sentences[best]))
    return (f"{heading_line}\n{window}" if heading_line else window), score


def discourse_window(text: str, claim: str, radius: int = 3) -> str:
    """Best-overlap sentence +/- radius sentences, prefixed by nearest preceding heading."""
    return discourse_window_scored(text, claim, radius)[0]


def _highlights_window(highlights: list[str]) -> str:
    """Label Exa excerpts while retaining the existing bounded judge input."""
    excerpts: list[str] = []
    used = 0
    for highlight in highlights:
        label = f"[Highlight {len(excerpts) + 1}]\n{highlight.strip()}"
        separator = 2 if excerpts else 0
        remaining = MAX_WINDOW_CHARS - used - separator
        if remaining <= 0:
            break
        excerpts.append(label[:remaining])
        used += separator + len(excerpts[-1])
    return "\n\n".join(excerpts)


def _merge_highlights(highlights: list[str], full_text: str | None) -> list[str]:
    """Deduplicate Exa snippets, preserving document order when text is cached."""
    unique: list[str] = []
    for highlight in highlights:
        cleaned = highlight.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    if full_text is None:
        return unique
    indexed = [
        (full_text.find(highlight), index, highlight)
        for index, highlight in enumerate(unique)
    ]
    return [
        highlight
        for _, _, highlight in sorted(
            indexed, key=lambda item: (item[0] < 0, item[0], item[1])
        )
    ]


class SourceFetcher:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        client: httpx.AsyncClient | None = None,
        daily_cap: DailyCallCap | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._daily_cap = daily_cap
        self._cache_dir = cache_dir
        self._client = client
        self._max_calls = _max_exa_calls()
        self._budget_logged = False
        self.budget_exhausted = False
        self.calls = 0
        self.cost_dollars = 0.0
        # url -> running fetch, shared with for_request children so concurrent
        # requests for one URL cost a single Exa call.
        self._inflight: dict[str, asyncio.Task[object]] = {}

    def for_request(self, max_calls: int = REQUEST_MAX_EXA_CALLS) -> "SourceFetcher":
        """Fresh per-request fetcher: own call budget, shared cache and daily cap."""
        child = SourceFetcher(
            self._api_key, self._cache_dir, self._client, self._daily_cap
        )
        child._max_calls = min(max_calls, self._max_calls)
        child._inflight = self._inflight
        return child

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def _read_entry(self, key: str) -> _CachedText | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            return _CachedText.model_validate_json(path.read_text())
        except (OSError, ValidationError):
            return None

    def _read_cache(self, key: str) -> str | None:
        entry = self._read_entry(key)
        return None if entry is None or entry.failed_at is not None else entry.text

    def _recently_failed(self, key: str) -> bool:
        entry = self._read_entry(key)
        return (
            entry is not None
            and entry.failed_at is not None
            and time.time() - entry.failed_at < NEGATIVE_CACHE_TTL_S
        )

    def _write_failure(self, key: str) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(key).write_text(
            _CachedText(text="", failed_at=time.time()).model_dump_json()
        )

    def cached_text(self, url: str) -> str | None:
        """Cached page text for url, or None; never calls the network."""
        return self._read_cache(url)

    def _write_cache(self, key: str, text: str) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(key).write_text(_CachedText(text=text).model_dump_json())

    @staticmethod
    def _highlights_key(url: str, query: str) -> str:
        return f"highlights\0{url}\0{query}"

    def _read_highlights(self, url: str, query: str) -> list[str] | None:
        cached = self._read_cache(self._highlights_key(url, query))
        if cached is None:
            return None
        try:
            parsed = json.loads(cached)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return parsed
        return None

    async def _contents(self, body: dict[str, object]) -> bytes | None:
        """One budgeted Exa contents request; errors remain retryable."""
        if self._api_key is None:
            return None
        if self.calls >= self._max_calls or (
            self._daily_cap is not None and not self._daily_cap.try_acquire()
        ):
            self.budget_exhausted = True
            if not self._budget_logged:
                self._budget_logged = True
                print(
                    f"EXA_MAX_CALLS={self._max_calls} reached; "
                    "further uncached sources are unavailable",
                    file=sys.stderr,
                )
            return None
        self.calls += 1
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                EXA_CONTENTS_URL,
                headers={"x-api-key": self._api_key},
                json=body,
                timeout=REQUEST_TIMEOUT_S,
            )
            response.raise_for_status()
            if response.status_code != 200:
                return None
            content = response.content
        except httpx.HTTPError:
            # Transport errors, 4xx/5xx (incl. 401/402/403/429) and malformed
            # bodies may succeed on retry: never negative-cache.
            return None
        finally:
            if self._client is None:
                await client.aclose()
        return content

    @staticmethod
    def _statuses_failed(parsed: _ExaResponse) -> bool:
        successes = {"success", "ok", "completed"}
        return any(
            status.error is not None
            or (status.status is not None and status.status.casefold() not in successes)
            for status in parsed.statuses
        )

    async def _fetch_text(self, url: str) -> _FetchOutcome:
        """One Exa call for url; text is None on any failure."""
        content = await self._contents({"urls": [url], "text": True})
        if content is None:
            return _FetchOutcome()
        try:
            parsed = _ExaResponse.model_validate_json(content)
        except ValidationError:
            return _FetchOutcome()
        if parsed.costDollars is not None:
            self.cost_dollars += parsed.costDollars.total
        if self._statuses_failed(parsed):
            return _FetchOutcome(permanent_failure=True)
        text = parsed.results[0].text if parsed.results else None
        return _FetchOutcome(
            text=text, permanent_failure=text is None or len(text) < MIN_TEXT_CHARS
        )

    async def _fetch_and_cache(self, url: str) -> str | None:
        outcome = await self._fetch_text(url)
        if outcome.text is not None and len(outcome.text) >= MIN_TEXT_CHARS:
            self._write_cache(url, outcome.text)
        elif outcome.permanent_failure:
            self._write_failure(url)
        return outcome.text

    async def _fetch_highlights(self, url: str, query: str) -> _HighlightsOutcome:
        content = await self._contents(
            {
                "urls": [url],
                "highlights": {"query": query, "maxCharacters": MAX_WINDOW_CHARS},
            }
        )
        if content is None:
            return _HighlightsOutcome()
        try:
            parsed = _ExaResponse.model_validate_json(content)
        except ValidationError:
            return _HighlightsOutcome()
        if parsed.costDollars is not None:
            self.cost_dollars += parsed.costDollars.total
        if self._statuses_failed(parsed):
            return _HighlightsOutcome(permanent_failure=True)
        highlights = parsed.results[0].highlights if parsed.results else []
        return _HighlightsOutcome(
            highlights=highlights, permanent_failure=not highlights
        )

    async def _fetch_highlights_and_cache(
        self, url: str, query: str
    ) -> list[str] | None:
        key = self._highlights_key(url, query)
        outcome = await self._fetch_highlights(url, query)
        if outcome.highlights:
            self._write_cache(key, json.dumps(outcome.highlights))
            return outcome.highlights
        if outcome.permanent_failure:
            self._write_failure(key)
        return None

    async def _shared_fetch(
        self, key: str, fetch: Callable[[], Coroutine[object, object, _T]]
    ) -> _T:
        """Fetch url once however many callers ask at the same time.

        Callers that join a running fetch spend no budget of their own.
        """
        task = self._inflight.get(key)
        if task is None:

            async def run() -> object:
                return await fetch()

            task = asyncio.create_task(run())
            self._inflight[key] = task

            def forget(done: "asyncio.Task[object]") -> None:
                if self._inflight.get(key) is done:
                    del self._inflight[key]

            self._inflight[key].add_done_callback(forget)
        # Shielded: one waiter being cancelled must not cancel the shared fetch.
        return cast(_T, await asyncio.shield(task))

    async def highlights(self, url: str, query: str) -> list[str] | None:
        """Query-specific Exa highlights with the same cache and call controls as text."""
        key = self._highlights_key(url, query)
        cached = self._read_highlights(url, query)
        if cached is not None:
            return cached
        if self._recently_failed(key):
            return None
        return await self._shared_fetch(
            key, lambda: self._fetch_highlights_and_cache(url, query)
        )

    async def source_text(self, url: str) -> str | None:
        """Return cached or fetched source text for checks requiring exact quotations."""
        text = self._read_cache(url)
        if text is not None or self._recently_failed(url):
            return text
        return await self._shared_fetch(url, lambda: self._fetch_and_cache(url))

    async def window(self, url: str, claim: str, radius: int = 3) -> SourceWindow:
        return (await self.window_scored(url, claim, radius))[0]

    async def window_scored(
        self,
        url: str,
        claim: str,
        radius: int = 3,
        on_text: Callable[[str], str | None] | None = None,
        old_claim: str | None = None,
        source_mode: Literal["highlights", "lexical"] = "lexical",
    ) -> tuple[SourceWindow, int]:
        """Window for url plus its claim-overlap score (0 when unavailable).

        on_text sees the raw page text and returns the text to window over,
        or None to treat the page as unavailable.
        """
        started = time.perf_counter()
        text = self._read_cache(url)
        if source_mode == "highlights":
            new_highlights = await self.highlights(url, claim)
            old_highlights = (
                await self.highlights(url, old_claim)
                if old_claim and old_claim != claim
                else None
            )
            highlights = _merge_highlights(
                (new_highlights or []) + (old_highlights or []), text
            )
            if on_text is not None:
                highlights = [
                    cleaned
                    for highlight in highlights
                    if (cleaned := on_text(highlight)) is not None
                ]
            window = _highlights_window(highlights)
            latency_ms = (time.perf_counter() - started) * 1000
            if window:
                return (
                    SourceWindow(
                        url=url,
                        status="ok",
                        text=window,
                        latency_ms=latency_ms,
                        method="highlights",
                    ),
                    len(highlights),
                )
        if text is None and not self._recently_failed(url):
            text = await self._shared_fetch(url, lambda: self._fetch_and_cache(url))
        if text is not None and on_text is not None:
            text = on_text(text)
        latency_ms = (time.perf_counter() - started) * 1000
        if text is None or len(text) < MIN_TEXT_CHARS:
            return (
                SourceWindow(
                    url=url, status="unavailable", text="", latency_ms=latency_ms
                ),
                0,
            )
        window, overlap = discourse_window_scored(text, claim, radius)
        if len(window) < MIN_WINDOW_CHARS or overlap < MIN_OVERLAP:
            return (
                SourceWindow(
                    url=url, status="unavailable", text="", latency_ms=latency_ms
                ),
                0,
            )
        return (
            SourceWindow(url=url, status="ok", text=window, latency_ms=latency_ms),
            overlap,
        )

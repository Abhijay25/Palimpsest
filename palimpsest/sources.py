"""Stage 1: Exa-backed citation source windows with a JSON-file cache."""

import hashlib
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

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
DEFAULT_MAX_EXA_CALLS: Final = 400
_SENTENCE_SPLIT: Final = re.compile(r"(?<=[.!?])\s+")
_TOKEN: Final = re.compile(r"\w+")
_HEADING: Final = re.compile(r"^#{1,6}\s")


class _CachedText(BaseModel):
    text: str


class _ExaResult(BaseModel):
    text: str | None = None


class _ExaCost(BaseModel):
    total: float = 0.0


class _ExaResponse(BaseModel):
    results: list[_ExaResult] = []
    costDollars: _ExaCost | None = None


def load_exa_api_key() -> str | None:
    """Read EXA_API_KEY from .env / environment; empty string counts as missing."""
    load_dotenv()
    return os.environ.get("EXA_API_KEY") or None


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


class SourceFetcher:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._cache_dir = cache_dir
        self._client = client
        self._max_calls = _max_exa_calls()
        self._budget_logged = False
        self.calls = 0
        self.cost_dollars = 0.0

    def _cache_path(self, url: str) -> Path:
        return self._cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            return _CachedText.model_validate_json(path.read_text()).text
        except (OSError, ValidationError):
            return None

    def _write_cache(self, url: str, text: str) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_text(_CachedText(text=text).model_dump_json())

    async def _fetch_text(self, url: str) -> str | None:
        """Return page text from Exa, or None on any failure."""
        if self._api_key is None:
            return None
        if self.calls >= self._max_calls:
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
                json={"urls": [url], "text": True},
                timeout=REQUEST_TIMEOUT_S,
            )
            response.raise_for_status()
            parsed = _ExaResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError):
            return None
        finally:
            if self._client is None:
                await client.aclose()
        if parsed.costDollars is not None:
            self.cost_dollars += parsed.costDollars.total
        if not parsed.results:
            return None
        return parsed.results[0].text

    async def window(self, url: str, claim: str, radius: int = 3) -> SourceWindow:
        return (await self.window_scored(url, claim, radius))[0]

    async def window_scored(
        self,
        url: str,
        claim: str,
        radius: int = 3,
        on_text: Callable[[str], str | None] | None = None,
    ) -> tuple[SourceWindow, int]:
        """Window for url plus its claim-overlap score (0 when unavailable).

        on_text sees the raw page text and returns the text to window over,
        or None to treat the page as unavailable.
        """
        started = time.perf_counter()
        text = self._read_cache(url)
        if text is None:
            text = await self._fetch_text(url)
            if text is not None and len(text) >= MIN_TEXT_CHARS:
                self._write_cache(url, text)
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

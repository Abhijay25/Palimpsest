import asyncio
import json
from pathlib import Path

import httpx
import pytest

from palimpsest.sources import SourceFetcher, discourse_window

SENTENCES = [
    f"Sentence number {i} talks about topic{i} in some detail here."
    for i in range(1, 11)
]
LONG_TEXT = " ".join(SENTENCES)
URL = "https://example.com/article"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _ok_handler(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": [{"text": LONG_TEXT}]})

    return httpx.MockTransport(handler)


def test_discourse_window_centres_on_best_sentence() -> None:
    window = discourse_window(LONG_TEXT, "topic6 detail")
    for i in range(3, 10):
        assert f"Sentence number {i} " in window
    assert "Sentence number 2 " not in window
    assert "Sentence number 10 " not in window


def test_discourse_window_prefixes_heading() -> None:
    text = "# Heading One\n\n" + LONG_TEXT
    assert discourse_window(text, "topic6").startswith("# Heading One")


def test_window_centres_on_best_sentence(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    fetcher = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    result = asyncio.run(fetcher.window(URL, "topic6 detail"))
    assert result.status == "ok"
    assert result.url == URL
    assert "Sentence number 3 " in result.text
    assert "Sentence number 9 " in result.text
    assert "Sentence number 2 " not in result.text
    assert calls[0].headers["x-api-key"] == "key"
    assert calls[0].url == "https://api.exa.ai/contents"
    assert json.loads(calls[0].content) == {"urls": [URL], "text": True}


def test_cache_hit_skips_network(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    fetcher = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    asyncio.run(fetcher.window(URL, "topic6"))
    second = asyncio.run(fetcher.window(URL, "topic6"))
    assert len(calls) == 1
    assert second.status == "ok"


def test_http_404_is_unavailable(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(404, json={}))
    result = asyncio.run(
        SourceFetcher("key", tmp_path, _client(transport)).window(URL, "x")
    )
    assert result.status == "unavailable"
    assert result.text == ""


def test_missing_key_is_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("network must not be called without a key")

    fetcher = SourceFetcher(None, tmp_path, _client(httpx.MockTransport(handler)))
    assert asyncio.run(fetcher.window(URL, "x")).status == "unavailable"


def test_short_text_is_unavailable(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"results": [{"text": "Too short."}]})
    )
    result = asyncio.run(
        SourceFetcher("key", tmp_path, _client(transport)).window(URL, "x")
    )
    assert result.status == "unavailable"


def test_empty_results_is_unavailable(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []}))
    result = asyncio.run(
        SourceFetcher("key", tmp_path, _client(transport)).window(URL, "x")
    )
    assert result.status == "unavailable"


def test_timeout_is_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    result = asyncio.run(
        SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler))).window(
            URL, "x"
        )
    )
    assert result.status == "unavailable"

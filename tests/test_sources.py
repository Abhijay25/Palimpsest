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
    asyncio.run(fetcher.window(URL, "topic6 detail"))
    second = asyncio.run(fetcher.window(URL, "topic6 detail"))
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


def test_call_budget_blocks_further_network_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EXA_MAX_CALLS", "2")
    calls: list[httpx.Request] = []
    fetcher = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    results = [
        asyncio.run(fetcher.window(f"https://example.com/{i}", "topic6 detail"))
        for i in range(4)
    ]
    assert [r.status for r in results] == ["ok", "ok", "unavailable", "unavailable"]
    assert len(calls) == 2
    assert fetcher.calls == 2
    assert capsys.readouterr().err.count("EXA_MAX_CALLS") == 1


def test_cache_hits_do_not_count_against_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXA_MAX_CALLS", "1")
    calls: list[httpx.Request] = []
    fetcher = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    asyncio.run(fetcher.window(URL, "topic6 detail"))
    assert asyncio.run(fetcher.window(URL, "topic6 detail")).status == "ok"
    assert fetcher.calls == 1


def test_cost_is_accumulated(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"text": LONG_TEXT}], "costDollars": {"total": 0.002}},
        )

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    asyncio.run(fetcher.window("https://example.com/1", "x"))
    asyncio.run(fetcher.window("https://example.com/2", "x"))
    assert fetcher.cost_dollars == pytest.approx(0.004)


def test_off_topic_window_is_unavailable(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    fetcher = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    result = asyncio.run(fetcher.window(URL, "Kanerva buried Lokalahti cemetery"))
    assert result.status == "unavailable"
    assert result.text == ""


def test_stub_page_window_is_unavailable(tmp_path: Path) -> None:
    stub = " ".join(["Vaalit Helsinki."] * 20)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"text": stub}]})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    result = asyncio.run(fetcher.window(URL, "Vaalit Helsinki Sauri"))
    assert result.status == "unavailable"

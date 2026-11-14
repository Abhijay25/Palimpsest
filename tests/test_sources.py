import asyncio
import datetime
import json
import time
from pathlib import Path

import httpx
import pytest

from palimpsest.sources import (
    NEGATIVE_CACHE_TTL_S,
    DailyCallCap,
    SourceFetcher,
    discourse_window,
)

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


def test_highlights_request_is_cached_and_labeled(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "results": [{"highlights": ["The census records 54,200 residents."]}],
                "statuses": [{"status": "success"}],
                "costDollars": {"total": 0.002},
            },
        )

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    first, _ = asyncio.run(
        fetcher.window_scored(URL, "54,200 residents", source_mode="highlights")
    )
    second, _ = asyncio.run(
        fetcher.window_scored(URL, "54,200 residents", source_mode="highlights")
    )
    assert json.loads(calls[0].content) == {
        "urls": [URL],
        "highlights": {"query": "54,200 residents", "maxCharacters": 4_000},
    }
    assert len(calls) == 1
    assert first.method == second.method == "highlights"
    assert first.text == "[Highlight 1]\nThe census records 54,200 residents."
    assert fetcher.cost_dollars == pytest.approx(0.002)


def test_failed_highlight_status_falls_back_to_lexical(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        if "highlights" in body:
            return httpx.Response(
                200,
                json={
                    "results": [{"highlights": ["wrong result"]}],
                    "statuses": [{"status": "error", "error": "unavailable"}],
                },
            )
        return httpx.Response(200, json={"results": [{"text": LONG_TEXT}]})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    result, _ = asyncio.run(
        fetcher.window_scored(URL, "topic6 detail", source_mode="highlights")
    )
    assert result.status == "ok"
    assert result.method == "lexical"
    assert len(calls) == 2


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


def test_for_request_has_own_budget_of_three(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    shared = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    first = shared.for_request()
    for i in range(5):
        asyncio.run(first.window(f"https://example.com/{i}", "topic6 detail"))
    assert len(calls) == 3
    assert first.budget_exhausted
    second = shared.for_request()
    asyncio.run(second.window("https://example.com/new", "topic6 detail"))
    assert len(calls) == 4
    assert not second.budget_exhausted


def test_daily_cap_blocks_across_requests_and_resets_at_utc_midnight(
    tmp_path: Path,
) -> None:
    day = [datetime.date(2026, 11, 14)]
    cap = DailyCallCap(2, today=lambda: day[0])
    calls: list[httpx.Request] = []
    shared = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)), cap)
    for i in range(4):
        asyncio.run(
            shared.for_request().window(f"https://example.com/{i}", "topic6 detail")
        )
    assert len(calls) == 2
    day[0] = datetime.date(2026, 11, 15)
    asyncio.run(shared.for_request().window("https://example.com/9", "topic6 detail"))
    assert len(calls) == 3


def test_failed_fetch_is_not_retried_within_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    assert asyncio.run(fetcher.window(URL, "x")).status == "unavailable"
    assert asyncio.run(fetcher.window(URL, "x")).status == "unavailable"
    assert len(calls) == 1
    assert fetcher.cached_text(URL) is None
    later = time.time() + NEGATIVE_CACHE_TTL_S + 1
    monkeypatch.setattr("palimpsest.sources.time.time", lambda: later)
    asyncio.run(fetcher.window(URL, "x"))
    assert len(calls) == 2


def test_budget_block_is_not_cached_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXA_MAX_CALLS", "0")
    calls: list[httpx.Request] = []
    blocked = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    assert asyncio.run(blocked.window(URL, "topic6 detail")).status == "unavailable"
    monkeypatch.setenv("EXA_MAX_CALLS", "5")
    fresh = SourceFetcher("key", tmp_path, _client(_ok_handler(calls)))
    assert asyncio.run(fresh.window(URL, "topic6 detail")).status == "ok"
    assert len(calls) == 1


def test_transient_failures_are_retried(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        if len(calls) == 2:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"results": [{"text": LONG_TEXT}]})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    assert asyncio.run(fetcher.window(URL, "topic6 detail")).status == "unavailable"
    assert asyncio.run(fetcher.window(URL, "topic6 detail")).status == "unavailable"
    assert asyncio.run(fetcher.window(URL, "topic6 detail")).status == "ok"
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 500, 503])
def test_http_error_statuses_are_never_negative_cached(
    tmp_path: Path, status: int
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    asyncio.run(fetcher.window(URL, "x"))
    asyncio.run(fetcher.window(URL, "x"))
    assert len(calls) == 2


def test_connect_error_and_bad_body_are_never_negative_cached(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"results": "not-a-list"})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    for _ in range(3):
        asyncio.run(fetcher.window(URL, "x"))
    assert len(calls) == 3


def test_stub_text_with_200_is_negative_cached(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": [{"text": "Too short."}]})

    fetcher = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    asyncio.run(fetcher.window(URL, "x"))
    asyncio.run(fetcher.window(URL, "x"))
    assert len(calls) == 1


def test_concurrent_requests_for_one_url_share_one_fetch(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"results": [{"text": LONG_TEXT}]})

    shared = SourceFetcher("key", tmp_path, _client(httpx.MockTransport(handler)))
    first, second = shared.for_request(1), shared.for_request(1)

    async def run() -> list[str]:
        results = await asyncio.gather(
            first.window(URL, "topic6 detail"),
            second.window(URL, "topic6 detail"),
            first.window(URL, "topic6 detail"),
        )
        return [r.status for r in results]

    assert asyncio.run(run()) == ["ok", "ok", "ok"]
    assert len(calls) == 1
    # Only the fetcher that actually called Exa spent budget.
    assert (first.calls, second.calls) == (1, 0)
    assert not second.budget_exhausted
    assert shared._inflight == {}

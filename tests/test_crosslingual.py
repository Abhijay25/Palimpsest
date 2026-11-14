import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from palimpsest import api
from palimpsest.crosslingual import (
    MEDIAWIKI_USER_AGENT,
    anchor_terms,
    cross_lingual_fanout,
    resolve_langlinks,
    select_paragraphs,
)
from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput, ExpandDirection, Verdict
from palimpsest.sources import SourceFetcher

TARGET_WIKITEXT = (
    "[[Ada Lovelace]] was born in 1815.<ref>https://example.org/ref</ref>\n\n"
    "This unrelated paragraph has no matching claims."
)
SOURCE_TEXT = "Ada Lovelace was born in 1815. " * 12


class FakeJudge:
    name = "fake"
    model = "fake-model"

    def __init__(self, verdict: Verdict = Verdict.CLEAN_PASS) -> None:
        self.verdict = verdict
        self.latencies_ms: dict[str, float] = {}

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        self.latencies_ms = {case.case.case_id: 1.0 for case in cases}
        output = AuditOutput(
            verdict=self.verdict,
            confidence=0.9,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=[],
            flagged_spans=[],
            neutral_rewrite=None,
        )
        return {case.case.case_id: output for case in cases}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _wiki_handler(request: httpx.Request) -> httpx.Response:
    prop = request.url.params.get("prop")
    if prop == "langlinks":
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Ada Lovelace",
                            "langlinks": [
                                {"lang": "de", "title": "Ada Lovelace"},
                                {"lang": "fr", "title": "Ada Lovelace"},
                            ],
                        }
                    ]
                }
            },
        )
    if request.method == "GET":
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "revisions": [
                                {"slots": {"main": {"content": TARGET_WIKITEXT}}}
                            ]
                        }
                    ]
                }
            },
        )
    return httpx.Response(
        200,
        json={"results": [{"text": SOURCE_TEXT}], "costDollars": {"total": 0}},
    )


def test_resolve_langlinks_parses_links_and_uses_required_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _wiki_handler(request)

    async def run() -> dict[str, str]:
        async with _client(handler) as client:
            return await resolve_langlinks(client, "en", "Ada Lovelace")

    assert asyncio.run(run()) == {"de": "Ada Lovelace", "fr": "Ada Lovelace"}
    assert dict(seen[0].url.params) == {
        "action": "query",
        "prop": "langlinks",
        "titles": "Ada Lovelace",
        "lllimit": "500",
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    }
    assert seen[0].headers["user-agent"] == MEDIAWIKI_USER_AGENT


def test_anchor_terms_and_paragraph_selection_use_neutral_anchors() -> None:
    anchors = anchor_terms(
        "Ada Lovelace entered [[Analytical Engine]] records in 1843."
    )
    assert "Ada" not in anchors
    assert {"Lovelace", "Analytical Engine", "1843"} <= anchors
    selected = select_paragraphs(
        "Opening 1843 only.\n\n[[Analytical Engine]] involved Lovelace in 1843.\n\nNone.",
        anchors,
    )
    assert selected == ["[[Analytical Engine]] involved Lovelace in 1843."]


@pytest.mark.parametrize(
    ("edit_verdict", "expected_warning"),
    [(Verdict.FLAG_G1_FACT, True), (Verdict.CLEAN_PASS, False)],
)
def test_fanout_divergence_rule(
    edit_verdict: Verdict,
    expected_warning: bool,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    async def run() -> bool:
        async with _client(_wiki_handler) as mediawiki:
            fetcher = SourceFetcher(
                "test-key", tmp_path_factory.mktemp("exa"), _client(_wiki_handler)
            )
            report = await cross_lingual_fanout(
                "en",
                "Ada Lovelace",
                "Ada Lovelace was born in 1815.",
                edit_verdict,
                FakeJudge(),
                fetcher,
                targets=["de", "fr"],
                client=mediawiki,
            )
            return report.divergence_warning

    assert asyncio.run(run()) is expected_warning


def test_fanout_marks_transport_error_unavailable(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def run() -> str:
        async with _client(broken) as mediawiki:
            fetcher = SourceFetcher(
                "test-key", tmp_path_factory.mktemp("exa"), _client(_wiki_handler)
            )
            report = await cross_lingual_fanout(
                "en",
                "Ada Lovelace",
                "Ada Lovelace 1815",
                Verdict.FLAG_G1_FACT,
                FakeJudge(),
                fetcher,
                targets=["de"],
                client=mediawiki,
            )
            return report.languages["de"].state

    assert asyncio.run(run()) == "UNAVAILABLE"


def test_cross_lingual_endpoint_requires_judge(tmp_path: Path) -> None:
    async def run() -> HTTPException:
        request = api.CrossLingualRequest(
            lang_code="en",
            page_title="Ada Lovelace",
            claim_text="Ada Lovelace was born in 1815.",
            edit_verdict=Verdict.FLAG_G1_FACT,
        )
        try:
            await api.cross_lingual(request, SourceFetcher(None, tmp_path), None)
        except HTTPException as exc:
            return exc
        raise AssertionError("expected an unavailable-judge response")

    assert asyncio.run(run()).status_code == 503

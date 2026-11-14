import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

import httpx
import pytest

from palimpsest import page_audit
from palimpsest.crosslingual import LanguageAuditState
from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput, Verdict


def _async_test[**P](
    function: Callable[P, Coroutine[object, object, None]],
) -> Callable[P, None]:
    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return wrapper


SWEDISH_MESSAGES = {
    "january": "januari",
    "february": "februari",
    "march": "mars",
    "april": "april",
    "may": "maj",
    "june": "juni",
    "july": "juli",
    "august": "augusti",
    "september": "september",
    "october": "oktober",
    "november": "november",
    "december": "december",
    "january-gen": "januari",
    "december-gen": "december",
    "dec": "dec",
}
FINNISH_MESSAGES = {
    "january": "tammikuu",
    "february": "helmikuu",
    "march": "maaliskuu",
    "april": "huhtikuu",
    "may": "toukokuu",
    "june": "kesäkuu",
    "july": "heinäkuu",
    "august": "elokuu",
    "september": "syyskuu",
    "october": "lokakuu",
    "november": "marraskuu",
    "december": "joulukuu",
    "january-gen": "tammikuuta",
    "december-gen": "joulukuuta",
    "dec": "joulu",
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(
    wikitext: str,
    rendered: str,
    messages: dict[str, str],
    old_timestamp: str | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("action") == "parse":
            return httpx.Response(200, json={"parse": {"text": rendered}})
        if params.get("meta") == "allmessages":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "allmessages": [
                            {"name": name, "content": value}
                            for name, value in messages.items()
                        ]
                        + [{"name": "unused-message", "missing": True}]
                    }
                },
            )
        if params.get("revids"):
            timestamp = old_timestamp or "2026-12-01T00:00:00Z"
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "revisions": [
                                    {"revid": 1261100216, "timestamp": timestamp}
                                ]
                            }
                        ]
                    }
                },
            )
        if params.get("rvslots"):
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {"revisions": [{"slots": {"main": {"content": wikitext}}}]}
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "revisions": [
                                {"revid": 99, "timestamp": "2026-01-01T12:00:00Z"}
                            ]
                        }
                    ]
                }
            },
        )

    return handler


@_async_test
async def test_allmessages_driven_swedish_and_finnish_textual_dates() -> None:
    page_audit._MONTH_CACHE.clear()
    async with _client(_handler("x", "<p>x</p>", SWEDISH_MESSAGES)) as client:
        swedish = await page_audit.month_names(client, "sv")
    async with _client(_handler("x", "<p>x</p>", FINNISH_MESSAGES)) as client:
        finnish = await page_audit.month_names(client, "fi")
    assert [
        value for _, value in page_audit.parsed_dates("4 december 2026", swedish)
    ] == [datetime(2026, 12, 4, tzinfo=UTC).date()]
    assert [
        value for _, value in page_audit.parsed_dates("4 tammikuuta 2026", finnish)
    ] == [datetime(2026, 1, 4, tzinfo=UTC).date()]


@_async_test
async def test_future_date_flags_only_dates_after_current_revision() -> None:
    page_audit._MONTH_CACHE.clear()
    html = "<p>Body 4 december 2026.</p><ol class='references'><li><cite>1 december 2025</cite></li></ol>"
    async with _client(_handler("Body", html, SWEDISH_MESSAGES)) as client:
        report = await page_audit.audit_page("sv", "Example", judge=None, client=client)
    assert [(item.rendered_date, item.location) for item in report.future_dates] == [
        ("4 december 2026", "body")
    ]


@_async_test
async def test_revision_date_mismatch_for_tornedalingar_style_citation() -> None:
    page_audit._MONTH_CACHE.clear()
    html = "<ol class='references'><li><cite>4 december 2026 <a href='https://en.wikipedia.org/w/index.php?title=X&amp;oldid=1261100216'>source</a></cite></li></ol>"
    async with _client(
        _handler("Text", html, SWEDISH_MESSAGES, "2024-12-04T00:00:00Z")
    ) as client:
        report = await page_audit.audit_page(
            "sv", "Tornedalingar", judge=None, client=client
        )
    assert len(report.revision_date_mismatches) == 1
    assert report.revision_date_mismatches[0].revid == 1261100216
    assert report.revision_date_mismatches[0].rendered_date == "4 december 2026"


class _FakeJudge:
    name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.latencies_ms: dict[str, float] = {}
        self.usage = {"calls": 2}

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        return {}


@_async_test
async def test_paragraph_cap_marks_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    page_audit._MONTH_CACHE.clear()

    async def fake_audit(*_: object) -> LanguageAuditState:
        return LanguageAuditState(
            lang="sv",
            state="AUDITED",
            verdict=Verdict.CLEAN_PASS,
            confidence=0.9,
            latency_ms=1.0,
        )

    monkeypatch.setattr(page_audit, "audit_single_language_claim", fake_audit)
    wikitext = "\n\n".join(
        f"Paragraph {n}<ref>https://example.org/{n}</ref>" for n in range(3)
    )
    async with _client(
        _handler(wikitext, "<p>Nothing</p>", SWEDISH_MESSAGES)
    ) as client:
        report = await page_audit.audit_page(
            "sv", "Example", max_paragraphs=2, judge=_FakeJudge(), client=client
        )
    assert (report.paragraphs_with_refs, report.paragraphs_audited, report.partial) == (
        3,
        2,
        True,
    )


@_async_test
async def test_no_judge_returns_only_deterministic_findings() -> None:
    page_audit._MONTH_CACHE.clear()
    async with _client(
        _handler("Text<ref>x</ref>", "<p>4 december 2026</p>", SWEDISH_MESSAGES)
    ) as client:
        report = await page_audit.audit_page("sv", "Example", judge=None, client=client)
    assert report.paragraph_audits == []
    assert report.paragraphs_audited == 0
    assert len(report.future_dates) == 1


def test_cli_writes_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report = page_audit.PageAuditReport(
        lang="sv",
        title="Example",
        revision_id=1,
        revision_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        stealth_status="CLEAN",
        stealth_findings=[],
        future_dates=[],
        revision_date_mismatches=[],
        paragraphs_total=1,
        paragraphs_with_refs=0,
        paragraphs_audited=0,
        partial=False,
        paragraph_audits=[],
    )

    async def fake_audit(*_: object, **__: object) -> page_audit.PageAuditReport:
        return report

    monkeypatch.setattr(page_audit, "audit_page", fake_audit)
    output = tmp_path / "report.json"
    assert (
        page_audit.main(
            ["--lang", "sv", "--title", "Example", "--no-judge", "--json", str(output)]
        )
        == 0
    )
    assert (
        page_audit.PageAuditReport.model_validate_json(output.read_text()).title
        == "Example"
    )

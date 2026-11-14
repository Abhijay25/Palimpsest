import asyncio
from collections.abc import Callable
from datetime import date

import httpx
import pytest

from palimpsest import api
from palimpsest.citation_lifecycle import CitationDriftReport, DriftStatus
from palimpsest.flags import citation_lifecycle_flags
from palimpsest.segment import EditUnit

URL = "https://source.test/article"
ARCHIVE_URL = (
    "https://web.archive.org/web/20200102030405id_/https://source.test/article"
)
BASELINE = "The council approved the harbour budget after a public vote."
CANDIDATE = [(URL, date(2020, 1, 2), "The council approved the harbour budget.")]


async def _public(_: str) -> bool:
    return True


async def _issuer(_: str) -> str | None:
    return None


def _handler(live: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "archive.org":
            return httpx.Response(
                200,
                json={
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "url": ARCHIVE_URL,
                            "status": "200",
                        }
                    }
                },
            )
        if str(request.url) == ARCHIVE_URL:
            return httpx.Response(200, text=BASELINE)
        return live(request)

    return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    ("live", "expected"),
    [
        (lambda _: httpx.Response(404, text="gone"), "HARD_LINK_ROT"),
        (
            lambda request: (
                httpx.Response(302, headers={"location": "/"})
                if request.url.path == "/article"
                else httpx.Response(200, text="home")
            ),
            "SOFT_404_REDIRECT",
        ),
        (
            lambda _: httpx.Response(
                200, text="Unrelated commercial material replaces every report."
            ),
            "SEMANTIC_RUGPULL",
        ),
    ],
)
def test_citation_lifecycle_scans_mocked_dead_redirect_and_drift(
    live: Callable[[httpx.Request], httpx.Response], expected: str
) -> None:
    async def run() -> api.CitationLifecycleScan:
        async with httpx.AsyncClient(transport=_handler(live)) as client:
            return await api.scan_citation_lifecycle(
                CANDIDATE,
                client=client,
                public_url_checker=_public,
                tls_issuer_resolver=_issuer,
            )

    result = asyncio.run(run())
    assert result.status == "ok"
    assert result.findings[0].drift_status == expected
    assert result.findings[0].wayback_fallback_url == ARCHIVE_URL


def test_citation_lifecycle_skips_a_url_without_a_wayback_baseline() -> None:
    async def run() -> api.CitationLifecycleScan:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"archived_snapshots": {}})
            )
        ) as client:
            return await api.scan_citation_lifecycle(
                CANDIDATE,
                client=client,
                public_url_checker=_public,
                tls_issuer_resolver=_issuer,
            )

    result = asyncio.run(run())
    assert result.status == "ok" and result.findings == []


def test_citation_lifecycle_includes_an_added_ref_on_an_unchanged_claim() -> None:
    old = "The council approved the budget."
    new = f"{old}<ref>{{{{cite web|url={URL}|access-date=2020-01-02}}}}</ref>"
    unit = EditUnit(
        index=0,
        old_text=old,
        new_text=old,
        old_wikitext=old,
        new_wikitext=new,
        kind="changed",
    )
    changed = api._unit_changed_refs(unit)
    assert changed == [URL]
    assert api._citation_lifecycle_candidates([unit], {0: changed}, {}) == [
        (URL, date(2020, 1, 2), old)
    ]


@pytest.mark.parametrize(
    ("parameter", "value", "months", "expected"),
    [
        ("access-date", "2020-11-12", {}, date(2020, 11, 12)),
        ("accessdate", "12 November 2020", {}, date(2020, 11, 12)),
        ("access_date", "November 12, 2020", {}, date(2020, 11, 12)),
        ("accessed", "12.11.2020", {}, date(2020, 11, 12)),
        ("luettu", "12 marraskuuta 2020", {"marraskuuta": 11}, date(2020, 11, 12)),
        ("hämtdatum", "12 november 2020", {"november": 11}, date(2020, 11, 12)),
        ("hämtad", "november 12, 2020", {"november": 11}, date(2020, 11, 12)),
    ],
)
def test_citation_lifecycle_accepts_local_access_parameter_names(
    parameter: str, value: str, months: dict[str, int], expected: date
) -> None:
    ref = f"<ref>{{{{cite web|url={URL}|{parameter}={value}}}}}</ref>"
    unit = EditUnit(
        index=0,
        old_text="Claim.",
        new_text="Claim.",
        old_wikitext="Claim.",
        new_wikitext=ref,
        kind="changed",
    )
    assert api._citation_lifecycle_candidates([unit], {0: [URL]}, months) == [
        (URL, expected, "Claim.")
    ]


def test_citation_lifecycle_isolates_one_failed_url() -> None:
    second = ("https://second.test/article", date(2020, 1, 2), "A claim.")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "archive.org":
            target = request.url.params["url"]
            if target == URL:
                return httpx.Response(500)
            return httpx.Response(
                200,
                json={
                    "archived_snapshots": {
                        "closest": {"available": True, "url": ARCHIVE_URL}
                    }
                },
            )
        if str(request.url) == ARCHIVE_URL:
            return httpx.Response(200, text=BASELINE)
        return httpx.Response(404)

    async def run() -> api.CitationLifecycleScan:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await api.scan_citation_lifecycle(
                [*CANDIDATE, second],
                client=client,
                public_url_checker=_public,
                tls_issuer_resolver=_issuer,
            )

    result = asyncio.run(run())
    assert result.status == "ok"
    assert result.findings[0].url == second[0]
    assert result.error is not None and URL in result.error


def test_citation_lifecycle_deadline_starts_with_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()

    async def stalled(
        candidates: list[tuple[str, date, str]],
    ) -> api.CitationLifecycleScan:
        await never.wait()
        return api.CitationLifecycleScan(status="ok")

    async def run() -> api.CitationLifecycleScan:
        started: asyncio.Future[float] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(api._scan_citation_lifecycle(CANDIDATE, started))
        await started
        return await api._await_completed_citation_lifecycle(task, started.result())

    monkeypatch.setattr(api, "CITATION_LIFECYCLE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(api, "scan_citation_lifecycle", stalled)
    assert asyncio.run(run()).error == "TimeoutError"


def test_citation_lifecycle_flags_anchor_and_map_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALIMPSEST_A1_DRIFT", "1")
    statuses: list[DriftStatus] = [
        "HARD_LINK_ROT",
        "SOFT_404_REDIRECT",
        "DOMAIN_HIJACK_SUSPECTED",
        "SEMANTIC_RUGPULL",
        "DELAYED_STEALTH_INJECTION",
    ]
    reports = [
        CitationDriftReport(
            url=f"https://source.test/{index}",
            drift_status=status,
            semantic_drift_score=1.0,
            still_entails_original_claim=None,
            wayback_fallback_url=ARCHIVE_URL,
            baseline_excerpt="The original report.",
            live_excerpt="The live response.",
            diff_summary="",
        )
        for index, status in enumerate(statuses)
    ]
    wikitext = " ".join(report.url for report in reports)
    flags = citation_lifecycle_flags(reports, wikitext)
    assert [flag.reason for flag in flags] == [
        "Cited page is no longer available",
        "Cited page now redirects to an unrelated page",
        "Cited site changed hands since it was cited",
        "Cited page changed substantially since it was cited",
        "Cited page gained hidden text since it was cited",
    ]
    assert flags[0].anchor_start == wikitext.index(reports[0].url)
    assert flags[0].evidence[0].url == ARCHIVE_URL
    assert flags[-1].tier == "admin" and flags[-1].check == "citation_lifecycle"


def test_whole_page_drift_is_not_flagged_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALIMPSEST_A1_DRIFT", raising=False)
    drift_statuses: list[DriftStatus] = ["SEMANTIC_RUGPULL", "DOMAIN_HIJACK_SUSPECTED"]
    reports = [
        CitationDriftReport(
            url="https://source.test/a",
            drift_status=status,
            semantic_drift_score=0.5,
            still_entails_original_claim=None,
            baseline_excerpt="Before.",
            live_excerpt="After.",
            diff_summary="Changed.",
        )
        for status in drift_statuses
    ]
    assert (
        citation_lifecycle_flags(reports, "Claim.<ref>https://source.test/a</ref>")
        == []
    )

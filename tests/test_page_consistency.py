import asyncio
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import cast

import httpx
import pytest

from palimpsest import api
from palimpsest.page_consistency import (
    CandidateGroup,
    PageConsistencyDecision,
    candidate_groups,
)
from palimpsest.sources import SourceFetcher


async def _direct_threadpool[**P, T](
    func: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    return func(*args, **kwargs)


class _DiffFetcher:
    budget_exhausted = False

    def for_request(self, max_calls: int = 3) -> "_DiffFetcher":
        return self

    def cached_text(self, url: str) -> None:
        return None


async def _no_auditor() -> None:
    return None


def _pairs(wikitext: str) -> set[tuple[str, str]]:
    return {
        (group.first.text, group.second.text) for group in candidate_groups(wikitext)
    }


@pytest.mark.parametrize(
    ("wikitext", "first", "second"),
    [
        (
            (
                "The North Bridge was completed in 1952.\n\n== History ==\n"
                "The North Bridge was completed in 1954."
            ),
            "The North Bridge was completed in 1952.",
            "The North Bridge was completed in 1954.",
        ),
        (
            (
                "Anna Virtanen syntyi 1. tammikuuta 1950.\n\n== Elämä ==\n"
                "Anna Virtanen syntyi 2. tammikuuta 1951."
            ),
            "Anna Virtanen syntyi 1. tammikuuta 1950.",
            "Anna Virtanen syntyi 2. tammikuuta 1951.",
        ),
        (
            (
                "Bron Norr är 120 meter lång.\n\n== Historia ==\n"
                "Bron Norr är 130 meter lång."
            ),
            "Bron Norr är 120 meter lång.",
            "Bron Norr är 130 meter lång.",
        ),
        (
            (
                "The River Bridge is located in Northport.\n\n== Route ==\n"
                "The River Bridge is located in Southport."
            ),
            "The River Bridge is located in Northport.",
            "The River Bridge is located in Southport.",
        ),
    ],
)
def test_candidate_groups_find_en_fi_sv_conflicts(
    wikitext: str, first: str, second: str
) -> None:
    assert (first, second) in _pairs(wikitext)


@pytest.mark.parametrize(
    "wikitext",
    [
        "The Delta Library was founded in 1952. The River Museum was founded in 1954.",
        "Jane Doe was born on 1 January 1952. Jane Doe died on 2 January 2020.",
        "Kaupunki perustettiin vuonna 1952. Museo perustettiin vuonna 1954.",
        "Anna föddes 1952. Anna dog 2020.",
    ],
)
def test_candidate_groups_reject_different_events_and_life_dates(wikitext: str) -> None:
    assert candidate_groups(wikitext) == []


class _StubJudge:
    calls = 0

    async def __call__(
        self, groups: Sequence[CandidateGroup]
    ) -> list[PageConsistencyDecision]:
        self.calls += 1
        return [
            PageConsistencyDecision(
                group_id=group.group_id,
                conflict=True,
                confidence=0.8,
                reason="The same bridge is assigned two incompatible completion years.",
            )
            for group in groups
        ]


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    api.app.dependency_overrides.clear()
    api.get_page_consistency_judge.cache_clear()
    yield
    api.app.dependency_overrides.clear()
    api.get_page_consistency_judge.cache_clear()


def _use_page_judge(judge: object) -> None:
    async def provider() -> object:
        return judge

    api.app.dependency_overrides[api.get_page_consistency_judge] = provider


async def _post_page(
    body: dict[str, object], headers: dict[str, str] | None = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/audit-page", json=body, headers=headers)


def test_audit_page_emits_existing_flag_shape_and_uses_one_judge_call() -> None:
    judge = _StubJudge()
    _use_page_judge(judge)
    response = asyncio.run(
        _post_page(
            {
                "lang_code": "en",
                "page_title": "North Bridge",
                "revision_id": 4,
                "wikitext": "The North Bridge was completed in 1952.\n\n"
                "== History ==\nThe North Bridge was completed in 1954.",
            }
        )
    )
    assert response.status_code == 200
    body = response.json()
    assert judge.calls == 1
    assert body["status"] == "ok"
    assert body["flags"][0]["kind"] == "OUT_OF_SYNC"
    assert body["flags"][0]["tier"] == "admin"
    assert body["flags"][0]["anchor_text"] == "The North Bridge was completed in 1952."
    assert (
        body["flags"][0]["related_anchor_text"]
        == "The North Bridge was completed in 1954."
    )
    assert body["flags"][0]["evidence"] == [
        {
            "source": "page",
            "quote": "The North Bridge was completed in 1954.",
            "url": "https://en.wikipedia.org/wiki/North_Bridge#History",
            "section": "History",
        }
    ]


def test_audit_page_cache_and_fresh_bypass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PALIMPSEST_RESULT_CACHE_DIR", str(tmp_path))
    judge = _StubJudge()
    _use_page_judge(judge)
    body = {
        "lang_code": "en",
        "page_title": "North Bridge",
        "revision_id": 4,
        "wikitext": "The North Bridge was completed in 1952.\n\n"
        "== History ==\nThe North Bridge was completed in 1954.",
    }

    async def post_all() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        return (
            await _post_page(body),
            await _post_page(body),
            await _post_page(body, {"X-Palimpsest-Fresh": "1"}),
        )

    first, second, fresh = asyncio.run(post_all())
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert fresh.json()["cached"] is False
    assert judge.calls == 2


def test_audit_diff_cache_and_fresh_bypass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PALIMPSEST_RESULT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(api, "run_in_threadpool", _direct_threadpool)
    request = api.AuditDiffRequest(
        lang_code="en",
        page_title="Example",
        old_revision_id=1,
        new_revision_id=2,
        editor_username="Cache test",
        old_text="The town has 500 people.",
        new_text="The town has 500 people.",
        ref_urls=[],
    )

    async def audit_all() -> tuple[
        api.AuditDiffResponse, api.AuditDiffResponse, api.AuditDiffResponse
    ]:
        fetcher = cast(SourceFetcher, _DiffFetcher())
        return (
            await api.audit_diff(request, fetcher, None, None, _no_auditor),
            await api.audit_diff(request, fetcher, None, None, _no_auditor),
            await api.audit_diff(request, fetcher, None, None, _no_auditor, fresh="1"),
        )

    first, second, fresh = asyncio.run(audit_all())
    assert first.cached is False
    assert second.cached is True
    assert fresh.cached is False


def test_audit_page_truncation_is_explicit() -> None:
    async def no_candidates(
        _: Sequence[CandidateGroup],
    ) -> list[PageConsistencyDecision]:
        return []

    _use_page_judge(no_candidates)
    wikitext = "No values here. " * 20_000
    response = asyncio.run(
        _post_page(
            {
                "lang_code": "en",
                "page_title": "Long page",
                "revision_id": 4,
                "wikitext": wikitext,
            }
        )
    )
    assert response.status_code == 200
    assert "truncated" in response.json()["error"]


def test_gemini_sends_strict_pydantic_schema_as_json_schema():
    from types import SimpleNamespace
    from palimpsest.backends.gemini import _GeminiCaller
    from palimpsest.page_consistency import PageConsistencyAnswers

    class Models:
        async def generate_content(self, *, model, contents, config):
            # extra="forbid" emits additionalProperties, which must use the
            # JSON Schema API rather than Gemini's legacy response_schema.
            assert config.response_schema is None
            assert config.response_json_schema['additionalProperties'] is False
            assert '$defs' in config.response_json_schema
            return SimpleNamespace(text='{"answers": []}')

    client=SimpleNamespace(aio=SimpleNamespace(models=Models()))
    caller=_GeminiCaller('configured-test-model',client,0)
    answer,_=asyncio.run(caller.generate('system','contents',PageConsistencyAnswers))
    assert isinstance(answer,PageConsistencyAnswers)


def test_page_judge_uses_configurable_bounded_deadline(monkeypatch):
    from types import SimpleNamespace
    from palimpsest.page_consistency import GeminiPageConsistencyJudge
    client=SimpleNamespace(aio=SimpleNamespace(models=object()))
    monkeypatch.setenv('PALIMPSEST_PAGE_TIMEOUT_SECONDS','65')
    judge=GeminiPageConsistencyJudge(client=client)
    assert judge.deadline == 65
    assert judge._caller.timeout == 65
    monkeypatch.setenv('PALIMPSEST_PAGE_TIMEOUT_SECONDS','999')
    assert GeminiPageConsistencyJudge(client=client).deadline == 75

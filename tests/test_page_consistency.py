import asyncio
import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from palimpsest import api, page_consistency
from palimpsest.page_consistency import (
    CandidateGroup,
    GeminiPageConsistencyJudge,
    PageConsistencyAnswers,
    PageConsistencyDecision,
    adjudicate_page,
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


def test_page_consistency_schema_is_accepted_by_gemini_response_schema() -> None:
    # Gemini's response_schema rejects additionalProperties (live 400 INVALID_ARGUMENT).
    schema = json.dumps(PageConsistencyAnswers.model_json_schema())
    assert "additionalProperties" not in schema
    assert "additional_properties" not in schema
    page_schema = json.dumps(
        page_consistency.WholePageConsistencyAnswers.model_json_schema()
    )
    assert "additionalProperties" not in page_schema


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


def test_audit_page_timeout_is_partial_and_not_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SlowCaller:
        calls = 0

        async def generate(
            self, *_: object
        ) -> tuple[PageConsistencyAnswers | str, float]:
            self.calls += 1
            await asyncio.sleep(1)
            return "unreachable", 0.0

    monkeypatch.setenv("PALIMPSEST_RESULT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(page_consistency, "DEADLINE_S", 0.001)
    caller = SlowCaller()
    _use_page_judge(GeminiPageConsistencyJudge(caller=cast(Any, caller)))
    body = {
        "lang_code": "en",
        "page_title": "North Bridge",
        "revision_id": 4,
        "wikitext": "The North Bridge was completed in 1952.\n\n"
        "== History ==\nThe North Bridge was completed in 1954.",
    }

    first, second = asyncio.run(_post_page(body)), asyncio.run(_post_page(body))
    for response in (first, second):
        payload = response.json()
        assert payload["status"] == "partial"
        assert payload["flags"]
        assert "TimeoutError" in payload["error"]
        assert payload["cached"] is False
    assert caller.calls == 4
    assert not list(tmp_path.iterdir())


def test_page_adjudication_batches_in_stable_order() -> None:
    class BatchJudge:
        def __init__(self) -> None:
            self.batches: list[tuple[str, ...]] = []

        async def __call__(
            self, groups: Sequence[CandidateGroup]
        ) -> list[PageConsistencyDecision]:
            self.batches.append(tuple(group.group_id for group in groups))
            await asyncio.sleep(0)
            return [
                PageConsistencyDecision(
                    group_id=group.group_id,
                    conflict=False,
                    confidence=0.0,
                    reason="No conflict.",
                )
                for group in reversed(groups)
            ]

    wikitext = " ".join(
        f"The North Bridge was completed in {1900 + year}." for year in range(9)
    )
    judge = BatchJudge()
    groups, decisions = asyncio.run(adjudicate_page(wikitext, judge))
    expected_ids = [group.group_id for group in groups]

    assert len(groups) > 28
    assert len(judge.batches) == 3
    assert [group_id for batch in judge.batches for group_id in batch] == expected_ids
    assert [decision.group_id for decision in decisions] == expected_ids

    repeated_groups, repeated_decisions = asyncio.run(adjudicate_page(wikitext, judge))
    assert [group.group_id for group in repeated_groups] == expected_ids
    assert [decision.group_id for decision in repeated_decisions] == expected_ids
    assert judge.batches[3:] == judge.batches[:3]


class _WholePageJudge:
    def __init__(self, conflicts: list[page_consistency.WholePageConflict]) -> None:
        self.conflicts = conflicts
        self.page_texts: list[str] = []

    async def __call__(
        self, groups: Sequence[CandidateGroup]
    ) -> list[PageConsistencyDecision]:
        return [
            PageConsistencyDecision(
                group_id=group.group_id,
                conflict=True,
                confidence=0.8,
                reason="Grouped conflict.",
            )
            for group in groups
        ]

    async def whole_page(
        self, page_text: str
    ) -> list[page_consistency.WholePageConflict]:
        self.page_texts.append(page_text)
        return self.conflicts


def _page_conflict(
    quote_a: str, quote_b: str, value_a: str, value_b: str
) -> page_consistency.WholePageConflict:
    return page_consistency.WholePageConflict(
        event_label="the bridge opening",
        quote_a=quote_a,
        quote_b=quote_b,
        value_a=value_a,
        value_b=value_b,
    )


def test_whole_page_pass_rejects_hallucinated_quotes() -> None:
    quote_a = "Silta avattiin vuonna 1952."
    quote_b = "Avajaiset pidettiin vuonna 1954."
    judge = _WholePageJudge(
        [_page_conflict("Hallusinoitu lause vuonna 1952.", quote_b, "1952", "1954")]
    )
    _use_page_judge(judge)
    response = asyncio.run(
        _post_page(
            {
                "lang_code": "fi",
                "page_title": "Silta",
                "revision_id": 4,
                "wikitext": f"{quote_a} {quote_b}",
            }
        )
    )

    assert response.status_code == 200
    assert response.json()["flags"] == []
    assert judge.page_texts == [f"{quote_a} {quote_b}"]


def test_whole_page_pass_dedupes_grouped_sentence_pair() -> None:
    quote_a = "The North Bridge was completed in 1952."
    quote_b = "The North Bridge was completed in 1954."
    judge = _WholePageJudge([_page_conflict(quote_a, quote_b, "1952", "1954")])
    _use_page_judge(judge)
    response = asyncio.run(
        _post_page(
            {
                "lang_code": "en",
                "page_title": "North Bridge",
                "revision_id": 4,
                "wikitext": f"{quote_a}\n\n== History ==\n{quote_b}",
            }
        )
    )

    assert response.status_code == 200
    assert len(response.json()["flags"]) == 1


def test_whole_page_pass_flags_are_stably_ordered() -> None:
    first_a = "A monument opened in 1952."
    first_b = "Its inauguration occurred in 1954."
    second_a = "A museum admitted 120 visitors."
    second_b = "The attendance total was 130 visitors."
    judge = _WholePageJudge(
        [
            _page_conflict(second_a, second_b, "120", "130"),
            _page_conflict(first_a, first_b, "1952", "1954"),
        ]
    )
    groups, decisions = asyncio.run(
        adjudicate_page(f"{first_a} {first_b} {second_a} {second_b}", judge)
    )

    assert [group.first.text for group in groups] == [first_a, second_a]
    assert [decision.group_id for decision in decisions] == ["p000", "p001"]


def test_whole_page_pass_normalises_grounded_quotes_and_values() -> None:
    quote_a = (
        "The North\u00adBridge opened on 14 December 2012 – with 4\u00a0932 visitors."
    )
    quote_b = "Later logs place it on 14.11.2012 — count 4933."
    judge = _WholePageJudge(
        [
            _page_conflict(
                "The [[North Bridge|NorthBridge]] opened on 14.12.2012 - with 4932 visitors.",
                "Later logs place it on 14.11.2012 - count 4933.",
                "14.12.2012",
                "14.11.2012",
            )
        ]
    )

    groups, _ = asyncio.run(adjudicate_page(f"{quote_a} {quote_b}", judge))

    assert [group.group_id for group in groups] == ["p000"]
    assert page_consistency._normalised_value("4\u00a0932") == "4932"
    assert page_consistency._normalised_value("14 December 2012") == "2012-12-14"
    assert page_consistency._normalised_value("14 joulukuuta 2012") == "2012-12-14"
    assert page_consistency._normalised_value("14 december 2012") == "2012-12-14"
    assert page_consistency._normalised_value("1936–1940") != "1936-1939"


def test_whole_page_pass_fuzzily_locates_a_split_sentence() -> None:
    quote_a = "Dr. North finished in 1952."
    quote_b = "Dr. Southern began in 1954."
    judge = _WholePageJudge([_page_conflict(quote_a, quote_b, "1952", "1954")])

    groups, _ = asyncio.run(adjudicate_page(f"{quote_a} {quote_b}", judge))

    assert [group.group_id for group in groups] == ["p000"]
    assert groups[0].first.text == "North finished in 1952."


def test_whole_page_pass_merges_two_overlapping_halves() -> None:
    first_a = "Start marker opened in 1952."
    first_b = "Start result confirmed in 1954."
    second_a = "End marker opened in 1962."
    second_b = "End result confirmed in 1964."
    conflicts = [
        _page_conflict(second_a, second_b, "1962", "1964"),
        _page_conflict(first_a, first_b, "1952", "1954"),
    ]

    class ChunkJudge(_WholePageJudge):
        def __init__(self) -> None:
            super().__init__(conflicts)
            self.active = 0
            self.max_active = 0

        async def whole_page(
            self, page_text: str
        ) -> list[page_consistency.WholePageConflict]:
            self.page_texts.append(page_text)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0)
            self.active -= 1
            return [
                conflict
                for conflict in self.conflicts
                if conflict.quote_a in page_text and conflict.quote_b in page_text
            ]

    judge = ChunkJudge()
    wikitext = (
        f"{first_a} {first_b} " + "Filler text. " * 4_700 + f"{second_a} {second_b}"
    )

    groups, decisions = asyncio.run(adjudicate_page(wikitext, judge))

    assert len(judge.page_texts) == 2
    assert judge.max_active == 2
    assert all(
        len(page_text) <= page_consistency.PAGE_PASS_MAX_CHARS
        for page_text in judge.page_texts
    )
    assert (
        judge.page_texts[0][-page_consistency.PAGE_PASS_OVERLAP_CHARS :]
        == (judge.page_texts[1][: page_consistency.PAGE_PASS_OVERLAP_CHARS])
    )
    assert [group.group_id for group in groups if group.group_id.startswith("p")] == [
        "p000",
        "p001",
    ]
    assert [
        decision.group_id for decision in decisions if decision.group_id.startswith("p")
    ] == [
        "p000",
        "p001",
    ]


def test_whole_page_failure_returns_partial_grouped_candidates() -> None:
    class FailingWholePageJudge(_WholePageJudge):
        async def whole_page(
            self, page_text: str
        ) -> list[page_consistency.WholePageConflict]:
            raise TimeoutError("whole-page pass timed out")

    _use_page_judge(FailingWholePageJudge([]))
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

    assert response.json()["status"] == "partial"
    assert response.json()["flags"]


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

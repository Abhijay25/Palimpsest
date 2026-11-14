import asyncio

import pytest

from palimpsest import consistency
from palimpsest.consistency import (
    ConsistencyFinding,
    article_url,
    check_page_consistency,
)
from palimpsest.flags import consistency_flags
from palimpsest.segment import EditUnit


def _unit(old: str, new: str) -> EditUnit:
    return EditUnit(
        index=0,
        old_text=old,
        new_text=new,
        old_wikitext=old,
        new_wikitext=new,
        kind="changed",
    )


async def _names(_: object, __: str) -> dict[str, int]:
    return {"monday": 100, "tuesday": 101, "maanantaina": 100, "tiistaina": 101}


def test_deterministic_prose_and_infobox_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consistency, "_localized_temporal_names", _names)

    async def run() -> None:
        prose = await check_page_consistency(
            "The Festival opened in 1997.\n\nThe Festival opened in 1997.",
            "The Festival opened in 2009.\n\n== History ==\nThe Festival opened in 1997.",
            [_unit("The Festival opened in 1997.", "The Festival opened in 2009.")],
            "en",
        )
        infobox = await check_page_consistency(
            "{{Infobox event|year=1997}}\nThe Festival opened in 1997.",
            "{{Infobox event|year=1997}}\nThe Festival opened in 2009.",
            [_unit("The Festival opened in 1997.", "The Festival opened in 2009.")],
            "en",
        )
        table = await check_page_consistency(
            "{|\n| Väkiluku (2009) || 12\n|}\nPopulation was 12.",
            "{|\n| Väkiluku (2009) || 12\n|}\nPopulation was 18.",
            [_unit("Population was 12.", "Population was 18.")],
            "en",
        )
        assert [(item.method, item.section) for item in prose] == [
            ("deterministic", "History")
        ]
        assert infobox[0].quote == "| year = 1997"
        assert table[0].quote == "Väkiluku (2009): 12"

    asyncio.run(run())


def test_localized_weekday_and_unrelated_old_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consistency, "_localized_temporal_names", _names)

    async def run() -> None:
        localized = await check_page_consistency(
            "The Festival was held maanantaina.\n\nThe Festival was held maanantaina.",
            "The Festival was held tiistaina.\n\nThe Festival was held maanantaina.",
            [
                _unit(
                    "The Festival was held maanantaina.",
                    "The Festival was held tiistaina.",
                )
            ],
            "fi",
        )
        unrelated = await check_page_consistency(
            "The Festival opened in 1997.\n\nThe archive was founded in 1997.",
            "The Festival opened in 2009.\n\nThe archive was founded in 1997.",
            [_unit("The Festival opened in 1997.", "The Festival opened in 2009.")],
            "en",
        )
        assert localized[0].old_value == "maanantaina"
        assert unrelated == []

    asyncio.run(run())


def test_semantic_quote_is_an_exact_page_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consistency, "_localized_temporal_names", _names)

    async def wrong(changed_sentence: str, candidates: list[str]) -> str:
        return "invented quote"

    async def exact(changed_sentence: str, candidates: list[str]) -> str:
        return candidates[0]

    async def run() -> None:
        old = "The Festival in Paris welcomed 1997 visitors.\n\nThe Festival in Paris welcomed many visitors."
        new = "The Festival in Paris welcomed 2009 visitors.\n\nThe Festival in Paris welcomed many visitors."
        unit = _unit(
            "The Festival in Paris welcomed 1997 visitors.",
            "The Festival in Paris welcomed 2009 visitors.",
        )
        assert await check_page_consistency(old, new, [unit], "en", wrong) == []
        finding = (await check_page_consistency(old, new, [unit], "en", exact))[0]
        assert finding.method == "semantic"
        assert finding.quote == "The Festival in Paris welcomed many visitors."

    asyncio.run(run())


def test_semantic_failure_and_deadline_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consistency, "_localized_temporal_names", _names)

    async def slow(changed_sentence: str, candidates: list[str]) -> str:
        await asyncio.sleep(0.05)
        return ""

    async def run() -> None:
        finding = await check_page_consistency(
            "The Festival in Paris welcomed 1997 visitors.\n\nThe Festival in Paris welcomed many visitors.",
            "The Festival in Paris welcomed 2009 visitors.\n\nThe Festival in Paris welcomed many visitors.",
            [
                _unit(
                    "The Festival in Paris welcomed 1997 visitors.",
                    "The Festival in Paris welcomed 2009 visitors.",
                )
            ],
            "en",
            slow,
            deadline_s=0.001,
        )
        assert finding == []

    asyncio.run(run())


def test_flag_mapping_has_page_jump_anchor() -> None:
    finding = ConsistencyFinding(
        0,
        "The event happened in 2009.",
        "The event happened in 1997.",
        "A section & more",
        "deterministic",
        "1997",
        "2009",
        False,
    )
    flags = consistency_flags([finding], "fi", "A title", "The event happened in 2009.")
    assert flags[0].kind == "OUT_OF_SYNC"
    assert flags[0].tier == "admin"
    assert flags[0].title == "Out of sync with the page: 2009 vs 1997"
    assert (
        flags[0].reason
        == "The edit changes 1997 to 2009, but the section 'A section & more' still says 1997."
    )
    assert flags[0].evidence[0].url == article_url("fi", "A title", "A section & more")
    assert flags[0].evidence[0].url.endswith("#A_section_%26_more")


def test_shared_judge_caller_is_not_reconfigured() -> None:
    from palimpsest.backends.gemini import GeminiJudgeBackend
    from palimpsest.consistency import gemini_consistency_judge

    backend = GeminiJudgeBackend(client=object())  # type: ignore[arg-type]  # never called
    before = (backend._caller.timeout, backend._caller.thinking)
    assert gemini_consistency_judge(backend) is not None
    assert (backend._caller.timeout, backend._caller.thinking) == before

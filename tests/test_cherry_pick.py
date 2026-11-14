import asyncio

from palimpsest.cherry_pick import (
    CherryPickAnalysis,
    CherryPickCandidate,
    analyze_cherry_pick,
    chunk_source,
    scan_cherry_picks,
    select_evidence,
)


def _paragraph(index: int, text: str) -> str:
    return f"Section {index}. {text} This paragraph supplies enough context for stable chunking."


def test_witnesses_claim_includes_late_forensic_conclusion() -> None:
    paragraphs = [
        _paragraph(index, f"Background evidence item {index} was recorded.")
        for index in range(12)
    ]
    paragraphs[2] = _paragraph(
        2, "Early witnesses alleged that the ballot stuffing occurred during counting."
    )
    paragraphs.append(
        _paragraph(
            12,
            "Forensic audits by four agencies concluded that ballot stuffing never occurred.",
        )
    )
    observed: list[str] = []

    async def judge(payload: str) -> CherryPickAnalysis:
        observed.append(payload)
        return CherryPickAnalysis(
            is_cherry_picked=True,
            cherry_pick_confidence=0.96,
            cited_chunk_id="c2",
            contradicting_chunk_ids=["c12"],
            source_overarching_conclusion="Four agencies found no ballot stuffing.",
            omitted_qualifiers_summary="The allegation was preliminary and refuted.",
            balanced_npov_rewrite="Early witnesses alleged ballot stuffing, but four agencies found none.",
        )

    result = asyncio.run(
        analyze_cherry_pick(
            "Witnesses alleged ballot stuffing occurred.",
            "\n\n".join(paragraphs),
            judge,
        )
    )

    assert result.is_cherry_picked
    assert '"cited_chunk": {"id": "c2"' in observed[0]
    assert '"conclusion_chunks": [{"id": "c11"' in observed[0]
    assert '"id": "c12"' in observed[0]


def test_consistent_source_is_not_flagged() -> None:
    source = "\n\n".join(
        [
            _paragraph(0, "The survey began in May with published methods."),
            _paragraph(1, "The survey found 61 percent support for the proposal."),
            _paragraph(
                2, "Its final report confirmed 61 percent support for the proposal."
            ),
        ]
    )

    async def judge(_: str) -> CherryPickAnalysis:
        return CherryPickAnalysis(
            is_cherry_picked=False,
            cherry_pick_confidence=0.08,
            cited_chunk_id="c1",
            contradicting_chunk_ids=[],
            source_overarching_conclusion="The final report confirmed the result.",
            omitted_qualifiers_summary="",
        )

    result = asyncio.run(
        analyze_cherry_pick("The survey found 61 percent support.", source, judge)
    )
    assert not result.is_cherry_picked
    assert result.contradicting_chunk_ids == []


def test_short_source_skips_the_judge() -> None:
    called = False

    async def judge(_: str) -> CherryPickAnalysis:
        nonlocal called
        called = True
        raise AssertionError("short sources must not reach the judge")

    result = asyncio.run(
        analyze_cherry_pick("A claim", "One paragraph.\n\nTwo paragraphs.", judge)
    )
    assert not result.is_cherry_picked
    assert result.cherry_pick_confidence == 0.0
    assert not called


def test_finnish_evidence_selection_needs_no_language_configuration() -> None:
    chunks = chunk_source(
        "\n\n".join(
            [
                _paragraph(0, "Taustatietoa tutkimuksesta julkaistiin keväällä."),
                _paragraph(
                    1, "Varhaiset todistajat väittivät vaalivilppiä tapahtuneen."
                ),
                _paragraph(2, "Lopullinen raportti käsitteli kaikki havainnot."),
                _paragraph(
                    3, "Neljä virastoa totesi lopulta, ettei vaalivilppiä tapahtunut."
                ),
            ]
        )
    )
    evidence = asyncio.run(
        select_evidence("Todistajat väittivät vaalivilppiä.", chunks)
    )
    assert evidence.cited_chunk.id == "c1"
    assert [chunk.id for chunk in evidence.conclusion_chunks] == ["c2", "c3"]


def test_chunking_is_stable_and_merges_tiny_paragraphs() -> None:
    text = "Tiny note.\n\n" + _paragraph(
        1, "A longer second paragraph follows the note."
    )
    first = chunk_source(text)
    second = chunk_source(text)
    assert [(chunk.id, chunk.index, chunk.text) for chunk in first] == [
        (chunk.id, chunk.index, chunk.text) for chunk in second
    ]
    assert len(first) == 1
    assert first[0].id == "c0"


class _Fetcher:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.queries: list[str] = []

    def cached_text(self, _: str) -> str | None:
        return self.text

    async def source_text(self, _: str) -> str | None:
        return self.text

    async def highlights(self, _: str, query: str) -> list[str] | None:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("Exa unavailable")
        return ["The final audit found the allegation unsupported."]


def test_quote_validation_routes_direct_source_quote_to_admin() -> None:
    source = "The final audit found the allegation unsupported."

    async def judge(_: str) -> CherryPickAnalysis:
        return CherryPickAnalysis(
            is_cherry_picked=True,
            cherry_pick_confidence=0.91,
            cited_chunk_id="c0",
            contradicting_chunk_ids=["c0"],
            source_overarching_conclusion="The allegation was unsupported.",
            omitted_qualifiers_summary="",
            contradicting_passages=[source],
        )

    report = asyncio.run(
        scan_cherry_picks(
            [
                CherryPickCandidate(
                    unit_index=3,
                    claim="The allegation was proven.",
                    url="https://example.test/source",
                    source_window=source,
                    citations=["https://example.test/source"],
                )
            ],
            _Fetcher(source),
            judge,
        )
    )

    assert report.status == "ok"
    assert report.findings[0].tier == "admin"
    assert report.findings[0].source_passage == source


def test_one_source_failure_is_recorded_without_raising() -> None:
    async def judge(_: str) -> CherryPickAnalysis:
        raise AssertionError("a failed highlights lookup must not reach the judge")

    report = asyncio.run(
        scan_cherry_picks(
            [
                CherryPickCandidate(
                    unit_index=0,
                    claim="A claim.",
                    url="https://example.test/source",
                    source_window="A source window.",
                    citations=["https://example.test/source"],
                )
            ],
            _Fetcher("A source window.", fail=True),
            judge,
        )
    )
    assert report.status == "unavailable"
    assert report.error is not None and "RuntimeError" in report.error

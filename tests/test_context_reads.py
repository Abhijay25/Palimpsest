import asyncio

from palimpsest.context_reads import (
    ContextCandidate,
    ContextRead,
    ContextReadBudget,
    apply_to_flag,
    classify,
    read_more,
)
from palimpsest.schema import Flag, FlagTier


class _Fetcher:
    def __init__(self, passages: list[str] | None = None) -> None:
        self.passages = passages or []
        self.calls: list[tuple[str, str]] = []

    async def highlights(self, url: str, query: str) -> list[str] | None:
        self.calls.append((url, query))
        return self.passages


def _flag(tier: FlagTier = "admin") -> Flag:
    return Flag(
        id="f1",
        kind="MOTIVE",
        tier=tier,
        title="Unsupported motive",
        reason="The source does not establish the motive.",
        confidence=0.8,
        side="new",
        anchor_text="to conceal fraud",
        anchor_start=0,
        anchor_end=15,
        context_sentence="The person acted to conceal fraud.",
        evidence=[],
        citations=["https://example.test/source"],
        neutral_rewrite=None,
        check="judge",
    )


def test_classifies_the_five_evidence_bases() -> None:
    assert (
        classify(ContextCandidate("MOTIVE", "to conceal fraud", "", ["u"])) == "ABSENCE"
    )
    assert (
        classify(ContextCandidate("REMOVED_CONTEXT", "although", "", ["u"]))
        == "REMOVED_CONTEXT"
    )
    assert classify(ContextCandidate("FACT", "x", "", ["u"], True)) == "CONTRADICTION"
    assert (
        classify(ContextCandidate("FRAMING", "ironically", "editorial voice", ["u"]))
        == "STYLE"
    )
    assert classify(ContextCandidate("MOTIVE", "x", "", [])) == "UNCITED"


def test_budget_and_deadline_bound_extra_highlights() -> None:
    fetcher = _Fetcher(["The person acted to conceal fraud."])
    candidate = ContextCandidate(
        "MOTIVE", "The person acted to conceal fraud.", "", ["u"]
    )
    budget = ContextReadBudget(max_calls=1)
    result = asyncio.run(read_more(candidate, fetcher, budget, "rule"))
    assert result.checked and result.supports_claim
    assert len(fetcher.calls) == budget.calls == 1

    expired = ContextReadBudget(deadline_s=0.0)
    result = asyncio.run(read_more(candidate, fetcher, expired, "rule"))
    assert not result.checked

    many_sources = ContextCandidate("MOTIVE", "claim", "", ["u1", "u2", "u3"])
    per_flag = ContextReadBudget()
    asyncio.run(read_more(many_sources, fetcher, per_flag, "rule"))
    assert per_flag.calls == 2


def test_support_demotes_absence_and_qualifier_promotes_removed_context() -> None:
    demoted = apply_to_flag(
        _flag(),
        ContextRead("ABSENCE", ["The person acted to conceal fraud."], True, True),
    )
    assert demoted.tier == "review"
    assert demoted.evidence[-1].quote == "The person acted to conceal fraud."

    removed = _flag("review").model_copy(update={"kind": "REMOVED_CONTEXT"})
    promoted = apply_to_flag(
        removed, ContextRead("REMOVED_CONTEXT", ["Although disputed."], True, True)
    )
    assert promoted.tier == "admin"


def test_rule_mode_never_reads_contradiction_style_or_uncited() -> None:
    fetcher = _Fetcher(["source"])
    budget = ContextReadBudget()
    for candidate in (
        ContextCandidate("FACT", "claim", "", ["u"], True),
        ContextCandidate("FRAMING", "ironically", "editorial voice", ["u"]),
        ContextCandidate("MOTIVE", "claim", "", []),
    ):
        result = asyncio.run(read_more(candidate, fetcher, budget, "rule"))
        assert not result.checked
    assert not fetcher.calls

import asyncio
import json

import pytest
from google.genai import types

from palimpsest.api import reviewer_enabled
from palimpsest.backends.gemini import GeminiReviewerBackend
from palimpsest.reviewer import (
    ReviewerAnswer,
    ReviewerAnswers,
    ReviewerCandidate,
    ReviewerDecision,
    review_candidates,
    review_unit_eligible,
)
from palimpsest.schema import AuditOutput, Flag, FlagEvidence


class _Fetcher:
    async def highlights(self, url: str, query: str) -> list[str] | None:
        return [f"The source supports {query}."]


class _Backend:
    model = "gemini-4-argon"

    def __init__(self, answers: ReviewerAnswers | str) -> None:
        self.answers = answers
        self.usage = {"input": 3, "output": 2, "thinking": 1}

    async def review(
        self, page_title: str, language: str, candidates: list[ReviewerCandidate]
    ) -> tuple[ReviewerAnswers | str, float]:
        return self.answers, 4.0


class _SlowBackend(_Backend):
    async def review(
        self, page_title: str, language: str, candidates: list[ReviewerCandidate]
    ) -> tuple[ReviewerAnswers | str, float]:
        await asyncio.sleep(1)
        return self.answers, 4.0


def _flag() -> Flag:
    return Flag(
        id="u0-s0",
        kind="MOTIVE",
        tier="admin",
        title="Original title",
        reason="Original reason",
        confidence=0.85,
        side="new",
        anchor_text="to conceal fraud",
        anchor_start=0,
        anchor_end=15,
        context_sentence="The edit says to conceal fraud.",
        evidence=[
            FlagEvidence(source="cited", quote="The source says there was no fraud.")
        ],
        citations=["https://example.test/source"],
        neutral_rewrite=None,
        check="judge",
        before="The person attended.",
        after="The person attended to conceal fraud.",
    )


def _answer(
    decision: ReviewerDecision = "to_review",
    reason: str = "The edit says to conceal fraud; the source says there was no fraud.",
) -> ReviewerAnswer:
    return ReviewerAnswer(
        candidate_id="u0-s0",
        decision=decision,
        title="Source does not establish a motive",
        reason=reason,
        edit_quote="to conceal fraud",
        source_quote="there was no fraud",
    )


def test_existing_candidates_are_never_deleted_or_raised_to_admin() -> None:
    result = asyncio.run(
        review_candidates(
            page_title="P",
            language="en",
            flags=[_flag()],
            borderline=[],
            fetcher=_Fetcher(),
            backend=_Backend(
                ReviewerAnswers(answers=[_answer("no_concern_for_borderline")])
            ),
        )
    )
    assert result.status == "ok"
    assert len(result.flags) == 1
    assert result.flags[0].tier == "review"


def test_valid_quotes_replace_reason_and_invalid_quotes_keep_it() -> None:
    valid = asyncio.run(
        review_candidates(
            page_title="P",
            language="en",
            flags=[_flag()],
            borderline=[],
            fetcher=_Fetcher(),
            backend=_Backend(ReviewerAnswers(answers=[_answer()])),
        )
    )
    assert valid.flags[0].reason.startswith("The edit says")
    invalid_answer = _answer(reason="The edit says invented words; the source agrees.")
    invalid = asyncio.run(
        review_candidates(
            page_title="P",
            language="en",
            flags=[_flag()],
            borderline=[],
            fetcher=_Fetcher(),
            backend=_Backend(ReviewerAnswers(answers=[invalid_answer])),
        )
    )
    assert invalid.flags[0].reason == "Original reason"
    assert invalid.flags[0].tier == "review"


def test_borderline_can_only_raise_to_review() -> None:
    candidate = ReviewerCandidate(
        candidate_id="u0-borderline",
        kind="FACT",
        edit_text="The population was 2009.",
        old_text="The population was 1997.",
        source_excerpts=["The source gives 1997."],
        title="Changed claim needs review",
        reason="The changed claim was not clearly supported.",
        is_value_change=True,
    )
    answer = ReviewerAnswer(
        candidate_id="u0-borderline",
        decision="raise_to_review",
        title="Changed population value",
        reason="The edit says 2009; the source gives 1997.",
        edit_quote="2009",
        source_quote="1997",
    )
    result = asyncio.run(
        review_candidates(
            page_title="P",
            language="en",
            flags=[],
            borderline=[candidate],
            fetcher=_Fetcher(),
            backend=_Backend(ReviewerAnswers(answers=[answer])),
        )
    )
    assert len(result.flags) == 1 and result.flags[0].tier == "review"


def test_reviewer_gate_only_allows_value_changes_or_detected_swaps() -> None:
    no_value_change = AuditOutput.model_validate(
        {
            "verdict": "FLAG_G2_FRAMING",
            "confidence": 0.8,
            "expand_direction": "NONE",
            "atomic_propositions": [],
            "flagged_spans": [
                {
                    "exact_substring": "notably",
                    "guideline_violated": "G2_FRAMING",
                    "explanation": "Editorial voice.",
                    "span_type": "EDITORIAL_VOICE",
                }
            ],
            "neutral_rewrite": None,
        }
    )
    typed_value_change = no_value_change.model_copy(
        update={
            "flagged_spans": [
                no_value_change.flagged_spans[0].model_copy(
                    update={"span_type": "VALUE_CHANGE"}
                )
            ]
        }
    )
    assert not review_unit_eligible(no_value_change, "They said it.", "They noted it.")
    assert review_unit_eligible(typed_value_change, "They said it.", "They noted it.")
    assert review_unit_eligible(no_value_change, "The count was 3.", "The count was 5.")


def test_deadline_and_backend_failure_leave_flags_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("palimpsest.reviewer.REVIEWER_TIMEOUT_S", 0.001)
    flag = _flag()
    result = asyncio.run(
        review_candidates(
            page_title="P",
            language="en",
            flags=[flag],
            borderline=[],
            fetcher=_Fetcher(),
            backend=_SlowBackend(ReviewerAnswers(answers=[])),
        )
    )
    assert result.status == "skipped"
    assert result.flags == [flag]


def test_api_reviewer_gate_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALIMPSEST_REVIEWER", raising=False)
    assert reviewer_enabled()
    monkeypatch.setenv("PALIMPSEST_REVIEWER", "0")
    assert not reviewer_enabled()


def test_reviewer_schema_has_no_additional_properties() -> None:
    from palimpsest.reviewer import ReviewerAnswers

    assert "additionalProperties" not in json.dumps(ReviewerAnswers.model_json_schema())


def test_argon_reviewer_is_pinned_to_low_thinking() -> None:
    backend = GeminiReviewerBackend(client=object())  # type: ignore[arg-type]
    assert backend.model == "gemini-4-argon"
    assert backend._caller.thinking is not None
    assert backend._caller.thinking.thinking_level == types.ThinkingLevel.LOW

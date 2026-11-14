import pytest

from palimpsest import diagnose
from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput


class FakeFetcher:
    budget_exhausted = False

    def for_request(self, max_calls: int = 3) -> "FakeFetcher":
        return self

    def cached_text(self, url: str) -> str | None:
        return None


class FakeJudge:
    name = "fake"
    model = "fake-model"

    def __init__(self, output: AuditOutput) -> None:
        self.output = output
        self.latencies_ms: dict[str, float] = {}

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        self.latencies_ms = {case.case.case_id: 1.0 for case in cases}
        return {case.case.case_id: self.output for case in cases}


async def _no_auditor() -> None:
    return None


def _configure(monkeypatch: pytest.MonkeyPatch, judge: FakeJudge | None) -> None:
    monkeypatch.setattr(diagnose, "get_fetcher", lambda: FakeFetcher())
    monkeypatch.setattr(diagnose, "get_judge_backend", lambda: judge)
    monkeypatch.setattr(diagnose, "get_auditor_provider", lambda: _no_auditor)


def test_stage0_clean_edit_prints_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(monkeypatch, None)

    assert (
        diagnose.main(
            [
                "--old",
                "The town has 500 people.",
                "--new",
                "The town has 500 people.",
                "--lang",
                "en",
                "--title",
                "Example",
            ]
        )
        == 0
    )

    assert "CLEAN_PASS" in capsys.readouterr().out


def test_nonclean_edit_without_judge_exits_three(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(monkeypatch, None)

    assert (
        diagnose.main(
            [
                "--old",
                "The mayor signed the bill.",
                "--new",
                "The mayor shamelessly pushed through the disastrous bill.",
                "--lang",
                "en",
                "--title",
                "Example",
            ]
        )
        == 3
    )

    assert "No judge is enabled" in capsys.readouterr().out


def test_table_includes_neutral_rewrite_from_fake_judge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = AuditOutput.model_validate(
        {
            "verdict": "FLAG_G2_FRAMING",
            "confidence": 0.8,
            "expand_direction": "NONE",
            "atomic_propositions": [],
            "flagged_spans": [],
            "neutral_rewrite": "The mayor signed the bill.",
        }
    )
    _configure(monkeypatch, FakeJudge(output))

    assert (
        diagnose.main(
            [
                "--old",
                "The mayor signed the bill.",
                "--new",
                "The mayor shamelessly pushed through the disastrous bill.",
                "--lang",
                "en",
                "--title",
                "Example",
            ]
        )
        == 0
    )

    assert "The mayor signed the bill." in capsys.readouterr().out


def test_table_includes_flagged_span_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = AuditOutput.model_validate(
        {
            "verdict": "FLAG_G2_FRAMING",
            "confidence": 0.8,
            "expand_direction": "NONE",
            "atomic_propositions": [],
            "flagged_spans": [
                {
                    "exact_substring": "shamelessly",
                    "guideline_violated": "G2_FRAMING",
                    "explanation": "loaded wording",
                }
            ],
            "neutral_rewrite": None,
        }
    )
    _configure(monkeypatch, FakeJudge(output))

    assert (
        diagnose.main(
            [
                "--old",
                "The mayor signed the bill.",
                "--new",
                "The mayor shamelessly pushed through the bill.",
                "--lang",
                "en",
                "--title",
                "Example",
            ]
        )
        == 0
    )

    assert (
        "context='The mayor shamelessly pushed through the bill.'"
        in capsys.readouterr().out
    )

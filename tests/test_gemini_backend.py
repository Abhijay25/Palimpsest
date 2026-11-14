import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from google.genai import errors, types

from palimpsest.backends.gemini import (
    GeminiClient,
    GeminiJudgeBackend,
    GeminiTriageBackend,
    gemini_enabled,
    load_gemini_api_key,
)
from palimpsest.judge import PreparedCase
from palimpsest.pipeline import ingest, prepare
from palimpsest.schema import Case, Verdict, dump_jsonl
from palimpsest.stage0 import Stage0Result
from palimpsest.stealth.models import HiddenFinding, VectorType

VALID_OUTPUT = {
    "verdict": "FLAG_G2_FRAMING",
    "confidence": 0.8,
    "expand_direction": "NONE",
    "atomic_propositions": [],
    "flagged_spans": [],
    "neutral_rewrite": "x",
}


class _Response:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, script: list[str | Exception]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _Response(step)


class _FakeAio:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class _FakeClient:
    def __init__(self, script: list[str | Exception]) -> None:
        self.models = _FakeModels(script)
        self.aio = _FakeAio(self.models)


def _prepared(case_id: str) -> PreparedCase:
    case = Case(
        case_id=case_id,
        lang="en",
        bucket="t",
        provenance="t",
        page_title="P",
        old_text="He said it.",
        new_text="He admitted it.",
        ref_urls=[],
        source_window="He said it on Monday.",
        expected=Verdict.FLAG_G2_FRAMING,
    )
    return PreparedCase(
        case=case,
        stage0=Stage0Result(clean=False, reasons=[], latency_ms=0.0),
        window=None,
    )


def _backend(script: list[str | Exception]) -> tuple[GeminiJudgeBackend, _FakeClient]:
    client = _FakeClient(script)
    return GeminiJudgeBackend(
        client=cast(GeminiClient, client), backoff_seconds=0.0
    ), client


def test_success_parses_and_records_latency() -> None:
    backend, client = _backend([json.dumps(VALID_OUTPUT)])
    out = asyncio.run(backend.judge([_prepared("a")]))
    result = out["a"]
    assert not isinstance(result, str)
    assert result.verdict == Verdict.FLAG_G2_FRAMING
    assert backend.latencies_ms["a"] >= 0.0
    call = client.models.calls[0]
    assert call["model"] == "gemini-4-hydrogen"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].temperature == 0
    assert "CASE a" in call["contents"]


def test_invalid_json_gives_error_string() -> None:
    backend, _ = _backend(["not json"])
    out = asyncio.run(backend.judge([_prepared("a")]))
    assert isinstance(out["a"], str) and out["a"]


def test_429_retried_once_then_success() -> None:
    err = errors.ClientError(429, {"error": {"message": "slow down"}})
    backend, client = _backend([err, json.dumps(VALID_OUTPUT)])
    out = asyncio.run(backend.judge([_prepared("a")]))
    assert not isinstance(out["a"], str)
    assert len(client.models.calls) == 2


def test_persistent_429_gives_error_after_one_retry() -> None:
    err = errors.ClientError(429, {"error": {"message": "slow down"}})
    backend, client = _backend([err, err])
    out = asyncio.run(backend.judge([_prepared("a")]))
    assert isinstance(out["a"], str)
    assert len(client.models.calls) == 2


def test_non_retryable_4xx_not_retried() -> None:
    err = errors.ClientError(400, {"error": {"message": "bad"}})
    backend, client = _backend([err])
    out = asyncio.run(backend.judge([_prepared("a")]))
    assert isinstance(out["a"], str)
    assert len(client.models.calls) == 1


def test_missing_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("palimpsest.backends.gemini.load_dotenv", lambda: False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        load_gemini_api_key()
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        GeminiJudgeBackend()


def test_thinking_level_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "LOW")
    backend, client = _backend([json.dumps(VALID_OUTPUT)])
    asyncio.run(backend.judge([_prepared("a")]))
    thinking = client.models.calls[0]["config"].thinking_config
    assert thinking is not None and str(thinking.thinking_level).endswith("LOW")


def test_triage_backend_parses_verdict() -> None:
    verdict = {
        "finding_id": "f1",
        "is_prompt_injection": True,
        "is_narrative_or_seo_cloaking": False,
        "is_benign_editor_note": False,
        "confidence": 0.9,
        "explanation": "x",
    }
    client = _FakeClient([json.dumps(verdict)])
    backend = GeminiTriageBackend(
        client=cast(GeminiClient, client), backoff_seconds=0.0
    )
    finding = HiddenFinding(
        vector_type=next(iter(VectorType)),
        raw_snippet="ignore previous",
        decoded_hidden_text="ignore previous",
        char_span=(0, 1),
        classification="NEEDS_TRIAGE",
        confidence=0.5,
        explanation="x",
    )
    out = asyncio.run(backend.triage([("f1", finding)]))
    assert not isinstance(out["f1"], str) and out["f1"].is_prompt_injection
    assert client.models.calls[0]["model"] == "gemini-decision-1"


def test_prepare_gemini_missing_key_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("palimpsest.backends.gemini.load_dotenv", lambda: False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        asyncio.run(prepare([], tmp_path / "run", [], backend="gemini"))


def test_prepare_gemini_roundtrips_through_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    cases = tmp_path / "c.jsonl"
    dump_jsonl(cases, [_prepared("a").case])
    backend, _ = _backend([json.dumps(VALID_OUTPUT)])
    run = tmp_path / "run"
    asyncio.run(prepare([cases], run, [], backend="gemini", gemini_backend=backend))
    ingest(run)
    rows = [
        json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()
    ]
    assert rows[0]["model"] == "gemini-4-hydrogen"
    assert rows[0]["stage_reached"] == 2
    assert rows[0]["stage2_ms"] >= 0.0


def test_gemini_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "set-but-not-approved")
    monkeypatch.delenv("PALIMPSEST_USE_GEMINI", raising=False)
    assert not gemini_enabled()
    with pytest.raises(SystemExit, match="PALIMPSEST_USE_GEMINI"):
        load_gemini_api_key()
    monkeypatch.setenv("PALIMPSEST_USE_GEMINI", "1")
    assert gemini_enabled()
    assert load_gemini_api_key() == "set-but-not-approved"


def test_judge_timed_returns_latencies_and_keeps_no_instance_state() -> None:
    backend, _ = _backend([json.dumps(VALID_OUTPUT)] * 2)

    async def run() -> list[tuple[object, dict[str, float]]]:
        return list(
            await asyncio.gather(
                backend.judge_timed([_prepared("same")]),
                backend.judge_timed([_prepared("same")]),
            )
        )

    runs = asyncio.run(run())
    assert all(set(latencies) == {"same"} for _, latencies in runs)
    assert backend.latencies_ms == {}


def test_usage_totals_are_recorded_from_response_metadata() -> None:
    from palimpsest.backends.gemini import _GeminiCaller

    class _Fake:
        usage_metadata = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=20, thoughts_token_count=7
        )

    caller = _GeminiCaller.__new__(_GeminiCaller)
    caller.usage = {"calls": 0, "input": 0, "output": 0, "thinking": 0}
    caller._record_usage(_Fake())  # type: ignore[arg-type]  # minimal stand-in for the SDK response
    caller._record_usage(_Fake())  # type: ignore[arg-type]  # minimal stand-in for the SDK response
    assert caller.usage == {"calls": 2, "input": 200, "output": 40, "thinking": 14}


def test_judge_defaults_to_low_thinking_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from palimpsest.backends.gemini import GeminiJudgeBackend

    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    judge = GeminiJudgeBackend(client=object())  # type: ignore[arg-type]  # no call is made
    assert judge._caller.thinking is not None
    assert judge._caller.thinking.thinking_level == types.ThinkingLevel.LOW
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "HIGH")
    judge = GeminiJudgeBackend(client=object())  # type: ignore[arg-type]  # no call is made
    assert judge._caller.thinking is not None
    assert judge._caller.thinking.thinking_level == types.ThinkingLevel.HIGH

import asyncio
import json
from pathlib import Path

import pytest

from palimpsest.judge import PreparedCase
from palimpsest.pipeline import ingest, prepare
from palimpsest.schema import Case, SourceWindow, Verdict, dump_jsonl, load_cases
from palimpsest.sources import SourceFetcher


def _case(case_id: str, source_window: str | None, refs: list[str]) -> Case:
    return Case(
        case_id=case_id,
        lang="en",
        bucket="t",
        provenance="t",
        page_title="P",
        old_text="He said it.",
        new_text="He admitted it.",
        ref_urls=refs,
        source_window=source_window,
        expected=Verdict.FLAG_G2_FRAMING,
    )


def test_prepare_statuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    cases = tmp_path / "c.jsonl"
    dump_jsonl(
        cases,
        [
            _case("fixed", "He said it on Monday.", []),
            _case("noref", None, []),
            _case("badref", None, ["https://example.invalid/x"]),
        ],
    )
    run = tmp_path / "run"
    asyncio.run(prepare([cases], run, ["haiku"]))
    rows = {
        pc.case.case_id: pc
        for pc in (
            PreparedCase.model_validate_json(line)
            for line in (run / "prepared.jsonl").read_text().splitlines()
        )
    }
    assert rows["fixed"].window is not None
    assert rows["fixed"].window.status == "fixed"
    assert rows["noref"].window is not None
    assert rows["noref"].window.status == "unavailable"
    assert rows["badref"].window is not None
    assert rows["badref"].window.status == "unavailable"
    assert (run / "batches" / "haiku" / "batch_001.md").exists()
    assert (run / "manifest.json").exists()
    assert len(load_cases(cases)) == 3


def test_prompt_version_and_batch_size_flow_to_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    monkeypatch.setattr("palimpsest.pipeline.PROMPTS_DIR", tmp_path)
    monkeypatch.setattr("palimpsest.judge.PROMPTS_DIR", tmp_path)
    (tmp_path / "subagent_judge.txt").write_text("write to {RESULTS_PATH}")
    (tmp_path / "stage2_test.txt").write_text("TEST RUBRIC")
    cases = tmp_path / "c.jsonl"
    dump_jsonl(cases, [_case(f"c{i}", "He said it on Monday.", []) for i in range(3)])
    run = tmp_path / "run"
    asyncio.run(prepare([cases], run, ["haiku"], "stage2_test", batch_size=1))
    batches = sorted((run / "batches" / "haiku").glob("*.md"))
    assert len(batches) == 3
    assert "TEST RUBRIC" in batches[0].read_text()
    ingest(run)
    rows = [
        json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()
    ]
    assert {r["prompt_version"] for r in rows} == {"stage2_test"}


def test_unknown_prompt_version_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        asyncio.run(prepare([], tmp_path / "run", ["haiku"], "stage2_nope"))


LONG_A = " ".join(f"Alpha sentence {i} covers apples and pears." for i in range(12))
LONG_B = " ".join(
    f"Beta sentence {i} covers waived fees in November." for i in range(12)
)


def _prime_cache(*pages: tuple[str, str]) -> None:
    fetcher = SourceFetcher(None, Path("cache/exa"))
    for url, text in pages:
        fetcher._write_cache(url, text)


def _window_status(tmp_path: Path, case: Case) -> SourceWindow:
    cases = tmp_path / "c.jsonl"
    dump_jsonl(cases, [case])
    run = tmp_path / "run"
    asyncio.run(prepare([cases], run, ["haiku"]))
    pc = PreparedCase.model_validate_json((run / "prepared.jsonl").read_text())
    assert pc.window is not None
    return pc.window


def test_empty_changed_ref_urls_is_uncited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    _prime_cache(("https://a.example/a", LONG_A))
    case = _case("c", None, ["https://a.example/a"])
    case.changed_ref_urls = []
    window = _window_status(tmp_path, case)
    assert window.status == "uncited"
    assert window.url is None


def test_best_overlap_window_among_changed_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    _prime_cache(("https://a.example/a", LONG_A), ("https://b.example/b", LONG_B))
    case = _case("c", None, ["https://a.example/a"])
    case.new_text = "Fees were waived in November."
    case.changed_ref_urls = ["https://a.example/a", "https://b.example/b"]
    window = _window_status(tmp_path, case)
    assert window.status == "ok"
    assert window.url == "https://b.example/b"


def test_none_changed_ref_urls_falls_back_to_ref_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palimpsest.pipeline.load_exa_api_key", lambda: None)
    _prime_cache(("https://a.example/a", LONG_A))
    window = _window_status(tmp_path, _case("c", None, ["https://a.example/a"]))
    assert window.status == "ok"
    assert window.url == "https://a.example/a"

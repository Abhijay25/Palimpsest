import asyncio
import json
from pathlib import Path

import pytest

from palimpsest.judge import PreparedCase
from palimpsest.pipeline import ingest, prepare
from palimpsest.schema import Case, Verdict, dump_jsonl, load_cases


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

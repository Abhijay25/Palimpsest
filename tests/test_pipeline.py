import asyncio
from pathlib import Path

import pytest

from palimpsest.judge import PreparedCase
from palimpsest.pipeline import prepare
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

"""Unit coverage for the offline security end-to-end harness."""

from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path

import pytest

from eval.security.build_cases import build_cases
from eval.security.poison_server import PAGE_CATALOG, page_html, start_server
from eval.security.run_e2e import (
    FlagSummary,
    bucket_summary,
    case_from_data,
    misses_markdown,
    score_case,
)

_PUFFERY = ("well-known", "famous", "renowned", "important", "notable")


def _status(port: int, path: str, timeout: float = 1.0) -> tuple[int, str | None]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Location")
    finally:
        connection.close()


def test_poison_catalogue_adds_only_the_hidden_payload() -> None:
    for name, spec in PAGE_CATALOG.items():
        benign = page_html(spec.lang)
        poisoned = page_html(name)
        assert benign is not None
        assert poisoned is not None
        assert spec.payload in poisoned
        assert poisoned.replace(spec.payload, "") == benign


def test_rot_endpoints_have_deterministic_statuses() -> None:
    try:
        server, thread = start_server(0)
    except PermissionError:
        pytest.skip("the current sandbox does not permit local listening sockets")
    port = int(server.server_address[1])
    try:
        assert _status(port, "/rot/404")[0] == 404
        assert _status(port, "/rot/500")[0] == 500
        assert _status(port, "/rot/moved")[0] == 200
        status, location = _status(port, "/rot/redirect-to-parking")
        assert (status, location) == (302, "/rot/parking")
        with pytest.raises((TimeoutError, socket.timeout)):
            _status(port, "/rot/hang", timeout=0.02)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_case_builder_has_complete_local_or_invalid_references(tmp_path: Path) -> None:
    paths = build_cases(8799, tmp_path)
    expected_counts = {
        "poison_edits": 26,
        "poison_cited": 12,
        "rot": 10,
        "controls": 15,
    }
    all_cases: list[dict[str, object]] = []
    for bucket, path in paths.items():
        cases = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(cases) == expected_counts[bucket]
        all_cases.extend(cases)
    required = {
        "case_id",
        "lang",
        "bucket",
        "page_title",
        "old_wikitext",
        "new_wikitext",
        "old_text",
        "new_text",
        "ref_urls",
        "expected",
        "notes",
    }
    assert len({str(case["case_id"]) for case in all_cases}) == len(all_cases)
    for case in all_cases:
        assert required <= set(case)
        assert case["lang"] in {"en", "fi", "sv"}
        expected = case["expected"]
        assert isinstance(expected, dict)
        assert set(expected) == {
            "must_flag_kinds",
            "accept_kinds",
            "min_tier",
            "must_not_flag_kinds",
        }
        assert expected["min_tier"] in {"admin", "review", "none"}
        refs = case["ref_urls"]
        assert isinstance(refs, list)
        assert all(
            url.startswith(
                ("http://127.0.0.1:8799/", "http://no-such-host-palimpsest.invalid/")
            )
            for url in refs
        )
        if case["bucket"] == "controls":
            prose = " ".join(
                str(case[key])
                for key in ("old_wikitext", "new_wikitext", "old_text", "new_text")
            ).casefold()
            assert not any(word in prose for word in _PUFFERY)


def _case(bucket: str = "poison_edits") -> object:
    return {
        "case_id": "synthetic",
        "lang": "en",
        "bucket": bucket,
        "page_title": "Synthetic page",
        "old_wikitext": "Old text.",
        "new_wikitext": "New text.",
        "old_text": "Old text.",
        "new_text": "New text.",
        "ref_urls": [],
        "expected": {
            "must_flag_kinds": ["CITED_PAGE"],
            "accept_kinds": [],
            "min_tier": "review",
            "must_not_flag_kinds": ["HIDDEN_TEXT"],
        },
        "notes": "Synthetic scorer fixture.",
    }


def test_scorer_requires_kind_and_tier_and_reports_false_positives() -> None:
    attack = case_from_data(_case())
    hit = score_case(
        attack,
        [FlagSummary("CITED_PAGE", "admin", "Cited page is unavailable")],
        0.2,
    )
    assert hit.hit and not hit.miss and not hit.false_positive

    prohibited = score_case(
        attack,
        [
            FlagSummary("CITED_PAGE", "review", "Cited page is unavailable"),
            FlagSummary("HIDDEN_TEXT", "review", "Unexpected extra finding"),
        ],
        0.4,
    )
    assert prohibited.hit and prohibited.false_positive

    control = case_from_data(_case("controls"))
    control_row = score_case(
        control,
        [FlagSummary("CITED_PAGE", "review", "Unexpected control flag")],
        0.6,
    )
    assert control_row.hit and control_row.false_positive
    summary = bucket_summary([hit, prohibited, control_row])
    assert summary["poison_edits"]["n"] == 2
    assert summary["controls"]["fp"] == 1
    report = misses_markdown([hit, prohibited, control_row])
    assert "synthetic" in report and "Unexpected extra finding" in report

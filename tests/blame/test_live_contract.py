"""Offline contract tests; transports are mocked and no sockets are opened."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from mediawiki_api import MediaWikiApiError, WikiApi
from verify_live import assert_spans, validate_analyze_schema
from verify_jobs import request_status
from seed_synthetic import DOCKER_PROJECT, load_manifest


class Response:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class QueueOpener:
    def __init__(self, *responses: dict) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return Response(self.responses.pop(0))


def ordinary_response(source_text: str) -> dict:
    return {
        "schema_version": 1,
        "status": "ready",
        "page": {"id": 1, "title": "Synthetic"},
        "snapshot": {"revision_id": 2, "parent_id": 1, "timestamp": "2026-01-02T00:00:00Z"},
        "coverage": {"history_complete": True, "provenance_status": "local"},
        "source_text": source_text,
        "html": "<p>ordinary fixture</p>",
        "spans": [],
        "revisions": [],
        "events": [],
        "algorithm": {"version": "test", "semantics": "last-change", "limits": {}},
        "mapping": {"mapped_characters": len(source_text), "unmapped_reasons": []},
    }


class LiveContractTests(unittest.TestCase):
    @staticmethod
    def runtime_manifest() -> dict:
        ports = {"fi": 48081, "sv": 48082, "en": 48083}
        return {
            "schema_version": 1,
            "project": DOCKER_PROJECT,
            "ports": ports,
            "languages": {lang: {"api_url": f"http://127.0.0.1:{port}/api.php"} for lang, port in ports.items()},
        }

    def test_runtime_manifest_accepts_exact_loopback_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps(self.runtime_manifest()), encoding="utf-8")
            loaded = load_manifest(path)
        self.assertEqual(loaded["project"], DOCKER_PROJECT)

    def test_runtime_manifest_rejects_non_exact_api_endpoints(self) -> None:
        for endpoint in (
            "http://example.test:48082/api.php",
            "https://127.0.0.1:48082/api.php",
            "http://127.0.0.1:48081/api.php",
            "http://127.0.0.1:48082/api.php?redirect=1",
        ):
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory() as directory:
                manifest = self.runtime_manifest()
                manifest["languages"]["sv"]["api_url"] = endpoint
                path = Path(directory) / "runtime.json"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exactly http://127.0.0.1:48082/api.php"):
                    load_manifest(path)

    def test_http_api_client_posts_form_fields_without_network(self) -> None:
        opener = QueueOpener({"edit": {"result": "Success", "newrevid": 73}})
        api = WikiApi("http://127.0.0.1:48081/api.php", opener=opener)
        result = api.call({"action": "edit", "title": "Synthetic/A", "text": "x", "token": "mock"}, post=True)
        request, timeout = opener.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertIn(b"title=Synthetic%2FA", request.data)
        self.assertEqual(timeout, 30)
        self.assertEqual(result["edit"]["newrevid"], 73)

    def test_ordinary_schema_passes_before_missing_schema_failure_is_asserted(self) -> None:
        ordinary = ordinary_response("ordinary fixture")
        self.assertEqual(validate_analyze_schema(ordinary), [])
        broken = copy.deepcopy(ordinary)
        del broken["snapshot"]
        errors = validate_analyze_schema(broken)
        self.assertEqual(errors, ["missing keys: snapshot"])

    def test_attribution_checker_accepts_ground_truth_then_rejects_wrong_revision(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "cross_contributor_deletion.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(validate_analyze_schema(ordinary_response(fixture["revisions"][-1]["text"])), [])
        ids = {"r1": 101, "r2": 102, "r3": 103, "r4": 104}
        correct = {
            "source_text": fixture["revisions"][-1]["text"],
            "spans": [
                {
                    "start": row["start"], "end": row["end"], "revision_id": ids[row["revision"]],
                    "token_id": f"{ids[row['revision']]}:{index}",
                    "lineage_ids": [f"{ids[row['revision']]}:{index}"],
                }
                for index, row in enumerate(fixture["expected"]["last_change_segments"])
            ],
        }
        assert_spans(correct, fixture["expected"]["last_change_segments"], ids)
        incorrect = copy.deepcopy(correct)
        incorrect["spans"][1]["revision_id"] = ids["r1"]
        incorrect["spans"][1]["token_id"] = f"{ids['r1']}:1"
        incorrect["spans"][1]["lineage_ids"] = [f"{ids['r1']}:1"]
        with self.assertRaisesRegex(AssertionError, "unexpected revision"):
            assert_spans(incorrect, fixture["expected"]["last_change_segments"], ids)

    def test_api_errors_report_code_without_logging_request_credentials(self) -> None:
        opener = QueueOpener({"error": {"code": "badtoken", "info": "Invalid token for must-not-appear"}})
        api = WikiApi("http://127.0.0.1:48081/api.php", opener=opener)
        with self.assertRaisesRegex(MediaWikiApiError, "badtoken"):
            api.call({"action": "edit", "password": "must-not-appear"}, post=True)
        self.assertNotIn("must-not-appear", str(MediaWikiApiError("badtoken", "must-not-appear")))

    def test_lineage_id_shape_rejects_revision_ids_instead_of_token_ids(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "chained_replacements.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(validate_analyze_schema(ordinary_response(fixture["revisions"][-1]["text"])), [])
        ids = {"r1": 101, "r2": 102, "r3": 103, "r4": 104, "r5": 105}
        segment = fixture["expected"]["last_change_segments"][1]
        result = {
            "source_text": fixture["revisions"][-1]["text"],
            "spans": [{"start": segment["start"], "end": segment["end"], "revision_id": ids[segment["revision"]], "token_id": ids[segment["revision"]], "lineage_ids": [ids[segment["revision"]]]}],
        }
        with self.assertRaisesRegex(AssertionError, "stable token ID"):
            assert_spans(result, [segment], ids)

    def test_coalesced_token_ranges_preserve_exact_utf16_ownership(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "coalesced_token_ranges.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        ids = fixture["revision_ids"]
        ordinary = ordinary_response(fixture["source_text"])
        ordinary["spans"] = copy.deepcopy(fixture["result"]["spans"])
        self.assertEqual(validate_analyze_schema(ordinary), [])
        segments = [dict(row) for row in fixture["expected_segments"]]
        assert_spans(ordinary, segments, ids)

        for name, error in (
            ("bad_gap", "not fully attributed"),
            ("bad_bounds", "invalid UTF-16 bounds"),
            ("bad_id_owner", "local revision"),
        ):
            broken = copy.deepcopy(ordinary)
            broken["spans"][0]["token_ranges"] = fixture["negative_cases"][name]["token_ranges"]
            self.assertEqual(validate_analyze_schema(broken), [])
            with self.subTest(case=name), self.assertRaisesRegex(AssertionError, error):
                assert_spans(broken, segments, ids)

    def test_job_status_uses_frozen_jobid_and_pinned_revision_parameters(self) -> None:
        class RecordingApi:
            def __init__(self) -> None:
                self.parameters = None

            def call(self, parameters):
                self.parameters = parameters
                return {"palimpsestblame": {"status": "pending", "revision_id": 205}}

        api = RecordingApi()
        result = request_status(api, "Synthetic/job page", 205, "opaque-job-id")
        self.assertEqual(result["revision_id"], 205)
        self.assertEqual(api.parameters, {
            "action": "palimpsestblame", "op": "status", "title": "Synthetic/job page",
            "revision": 205, "jobid": "opaque-job-id",
        })


if __name__ == "__main__":
    unittest.main()

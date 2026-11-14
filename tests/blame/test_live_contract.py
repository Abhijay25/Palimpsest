"""Offline contract tests; transports are mocked and no sockets are opened."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from mediawiki_api import MediaWikiApiError, WikiApi
from verify_live import assert_spans, validate_analyze_schema
from verify_jobs import request_status


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

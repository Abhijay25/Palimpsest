from __future__ import annotations

import copy
import hashlib
import unittest

from tests.infra.fixtures import pipeline_fixture
from tests.infra.oracle import audit_pipeline, runtime_is_ready, validate_corpus, validate_runtime, verify_release_assets


def runtime_fixture() -> dict:
    return {
        "schema_version": 1,
        "project": "palimpsest-c-fixture",
        "data_root": "/tmp/palimpsest-c-fixture",
        "ports": {"fi": 38081, "sv": 38082, "en": 38083},
        "languages": {
            language: {
                "api_url": f"http://127.0.0.1:{port}/w/api.php",
                "service": f"{language}-wiki",
                "database": f"{language}wiki",
            }
            for language, port in (("fi", 38081), ("sv", 38082), ("en", 38083))
        },
        "versions": {"mediawiki": "1.46.2", "mariadb": "11.8.9"},
        "initialized": {"fi": True, "sv": True, "en": True},
    }


class RuntimeManifestTests(unittest.TestCase):
    def test_accepts_local_routes_for_all_three_initialized_wikis(self) -> None:
        self.assertEqual(validate_runtime(runtime_fixture(), "palimpsest-c-fixture"), [])
        self.assertTrue(runtime_is_ready(runtime_fixture(), "palimpsest-c-fixture"))

    def test_rejects_wrong_route_and_secret_but_preserves_uninitialized_state(self) -> None:
        manifest = runtime_fixture()
        manifest["languages"]["sv"]["api_url"] = "https://example.com/w/api.php"
        manifest["versions"]["access_token"] = "must-not-be-published"
        manifest["initialized"]["en"] = False
        errors = validate_runtime(manifest)
        self.assertTrue(any("localhost" in error for error in errors), errors)
        self.assertTrue(any("credential" in error for error in errors), errors)
        # Readiness is represented as state; C1 may describe an uninitialized service,
        # while consumers must refuse to call it ready. The manifest itself stays valid.
        manifest.pop("versions")["mediawiki"]
        manifest["versions"] = {"mediawiki": "1.46.2"}
        manifest["languages"]["sv"]["api_url"] = "http://127.0.0.1:38082/w/api.php"
        self.assertEqual(validate_runtime(manifest), [])
        self.assertFalse(runtime_is_ready(manifest))
        self.assertTrue(any("expected project" in error for error in validate_runtime(manifest, "another-project")))


class CorpusAndPipelineTests(unittest.TestCase):
    def test_three_language_sample_reconciles_against_independent_source_inventory(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        self.assertEqual(validate_corpus(corpus), [])
        self.assertEqual(audit_pipeline(corpus, expected, history, imports, report), [])

    def test_duplicate_page_membership_and_conflicting_source_body_fail(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        duplicate = copy.deepcopy(corpus["articles"][0])
        corpus["articles"].append(duplicate)
        corpus["expected_counts"]["fi"] = 2
        self.assertTrue(any("duplicate source page" in e for e in validate_corpus(corpus)))

        corpus, expected, history, imports, report = pipeline_fixture()
        conflict = copy.deepcopy(history[0])
        conflict["computed_sha256"] = "different-body-hash"
        history.append(conflict)
        self.assertTrue(any("conflicting content" in e for e in audit_pipeline(corpus, expected, history, imports, report)))

    def test_self_consistent_history_and_import_forgery_is_compared_to_source_fixture(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        forged_text = "altered body with a freshly recomputed hash"
        forged_hash = hashlib.sha256(forged_text.encode("utf-8")).hexdigest()
        history[0]["content"] = forged_text
        history[0]["computed_sha256"] = forged_hash
        history[0]["timestamp"] = "2025-08-01T10:00:09Z"
        history[0]["author"]["value"] = "forged-author"
        imports[0]["source_content_hash"] = forged_hash
        imports[0]["timestamp"] = "2025-08-01T10:00:09Z"
        imports[0]["author"]["value"] = "forged-author"
        errors = audit_pipeline(corpus, expected, history, imports, report)
        self.assertTrue(any("C3 content differs from source" in e for e in errors), errors)
        self.assertTrue(any("C3 timestamp differs from source" in e for e in errors), errors)
        self.assertTrue(any("C3 author differs from source" in e for e in errors), errors)
        self.assertTrue(any("C4 timestamp differs from source" in e for e in errors), errors)
        self.assertTrue(any("C4 author.value differs from source" in e for e in errors), errors)

    def test_tiny_corpus_cannot_claim_full_scope(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        corpus["scope"] = "full"
        corpus["expected_counts"] = {"fi": 1, "sv": 1, "en": 1}
        self.assertTrue(any("published per-language S counts" in e for e in validate_corpus(corpus)))

    def test_release_asset_bytes_must_match_locked_size_and_sha256(self) -> None:
        raw = b"isolated parquet fixture bytes"
        digest = hashlib.sha256(raw).hexdigest()
        release = {"assets": [{"name": "sample.parquet", "url": "https://example.invalid/sample.parquet", "size": len(raw), "sha256": digest}]}
        self.assertEqual(verify_release_assets(release, {"sample.parquet": raw}), [])
        errors = verify_release_assets(release, {"sample.parquet": raw + b"!"})
        self.assertTrue(any("size differs" in e for e in errors), errors)
        self.assertTrue(any("SHA-256 differs" in e for e in errors), errors)

    def test_missing_history_or_mapping_fails_even_if_report_claims_complete(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        broken_history = copy.deepcopy(history)
        broken_history.pop(0)
        broken_report = copy.deepcopy(report)
        broken_report["per_language"]["fi"]["acquired_revisions"] = 1
        errors = audit_pipeline(corpus, expected, broken_history, imports, broken_report)
        self.assertTrue(any("missing source revisions" in e for e in errors), errors)
        self.assertTrue(any("complete=True" in e for e in errors), errors)

        corpus, expected, history, imports, report = pipeline_fixture()
        broken_imports = copy.deepcopy(imports)
        broken_imports.pop(0)
        broken_report = copy.deepcopy(report)
        broken_report["per_language"]["fi"]["imported_revisions"] = 1
        broken_report["per_language"]["fi"]["reconciled_revisions"] = 1
        broken_report["per_language"]["fi"]["reconciled_articles"] = 0
        broken_report["per_language"]["fi"]["unresolved_pages"] = 1
        broken_report["per_language"]["fi"]["unresolved_revisions"] = 1
        errors = audit_pipeline(corpus, expected, history, broken_imports, broken_report)
        self.assertTrue(any("missing source mappings" in e for e in errors), errors)
        self.assertTrue(any("complete=True" in e for e in errors), errors)

    def test_hidden_content_cannot_be_confused_with_visible_empty_text(self) -> None:
        corpus, expected, history, imports, report = pipeline_fixture()
        history[0]["content"] = None
        history[0]["content_hidden"] = False
        self.assertTrue(any("visible content is unavailable" in e for e in audit_pipeline(corpus, expected, history, imports, report)))

        corpus, expected, history, imports, report = pipeline_fixture()
        history[0]["content_hidden"] = True
        history[0]["content"] = "should be absent"
        history[0]["content_ref"] = "verified-ref-does-not-override-hidden-content"
        self.assertTrue(any("hidden content is exposed" in e for e in audit_pipeline(corpus, expected, history, imports, report)))

        corpus, expected, history, imports, report = pipeline_fixture()
        history[0]["content"] = ""
        history[0]["content_hidden"] = False
        self.assertEqual(audit_pipeline(corpus, expected, history, imports, report), [])


if __name__ == "__main__":
    unittest.main()

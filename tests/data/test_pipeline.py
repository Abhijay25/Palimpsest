from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from scripts.palimpsest_data.coverage import build_coverage, exit_for_report
from scripts.palimpsest_data.cli import _manifest_for
from scripts.palimpsest_data.dataset import fetch_assets
from scripts.palimpsest_data.history import GIB, acquire_article, acquire_corpus, fetch_json, revision_record
from scripts.palimpsest_data.io import DataError, atomic_json, canonical_json, iter_jsonl, sha256_bytes
from scripts.palimpsest_data.manifests import validate_corpus
from scripts.palimpsest_data.support import discover_support
from scripts.palimpsest_data.xml_export import export_article, export_article_stream, mediawiki_xml
from scripts.palimpsest_data.importer import fetch_local_page, import_corpus, map_revisions
import xml.etree.ElementTree as ET


def corpus_article(lang="fi", page=101, anchor=3000):
    return {"source_wiki": f"{lang}wiki", "language": lang, "source_page_id": page,
            "anchor_revision_id": anchor, "title": "Example & Test", "source_url": f"https://{lang}.wikipedia.org/?curid={page}",
            "wikidata_id": None, "dataset_timestamp": "2025-08-01T00:00:00Z"}


def sample_corpus():
    articles = [corpus_article(lang, 100 + i, 3000 + i) for i, lang in enumerate(("fi", "sv", "en"))]
    return {"schema_version": 1, "release": {"repository": "MariaDB/mariadb-wikipedia-datasets", "tag": "s-2026-10", "assets": []},
            "scope": "sample", "expected_counts": {"fi": 1, "sv": 1, "en": 1}, "articles": articles}


def rev(revid, timestamp, content, parentid=0):
    return {"revid": revid, "parentid": parentid, "timestamp": timestamp, "user": "Editor",
            "comment": "edit", "slots": {"main": {"content": content, "contentmodel": "wikitext", "contentformat": "text/x-wiki"}}}


class FakeApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected extra API request")
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


class DataPipelineTests(unittest.TestCase):
    def test_all_pages_selects_full_manifest_without_implicit_default(self):
        from argparse import Namespace
        root = Path("/data")
        self.assertEqual(_manifest_for(Namespace(sample_manifest=None, data_root=root, all_pages=False)),
                         root / "dataset" / "manifests" / "sample-corpus.json")
        self.assertEqual(_manifest_for(Namespace(sample_manifest=None, data_root=root, all_pages=True)),
                         root / "dataset" / "manifests" / "full-corpus.json")

    def test_local_api_url_accepts_runtime_root_api_endpoint(self):
        urls = []
        def api(url):
            urls.append(url)
            return {"query": {"pages": [{"pageid": 9, "revisions": []}]}}
        page_id, rows = fetch_local_page("http://127.0.0.1:28081/api.php", "Example", api=api)
        self.assertEqual(page_id, 9)
        self.assertEqual(rows, [])
        self.assertIn("/api.php?", urls[0])
        self.assertNotIn("/api.php/w/api.php", urls[0])

    def test_full_acquisition_requires_opt_in_then_uses_fake_api(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        corpus = sample_corpus()
        corpus["scope"] = "full"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "full.json"
            path.write_text(json.dumps(corpus))
            with patch("scripts.palimpsest_data.history.validate_corpus", return_value=corpus):
                with self.assertRaisesRegex(DataError, "requires explicit --all-pages"):
                    acquire_corpus(path, Path(temp) / "history")
                def api(url):
                    from urllib.parse import parse_qs, urlparse
                    page_id = int(parse_qs(urlparse(url).query)["pageids"][0])
                    article = next(x for x in corpus["articles"] if x["source_page_id"] == page_id)
                    return {"query": {"pages": [{"pageid": page_id, "revisions": [rev(article["anchor_revision_id"], article["dataset_timestamp"], "body")] }]}}
                result = acquire_corpus(path, Path(temp) / "history", allow_full=True, api=api, sleep=lambda _: None,
                                       interval=0, min_free_bytes=50 * GIB,
                                       disk_usage=lambda _: SimpleNamespace(free=51 * GIB))
                self.assertEqual(len(result["articles"]), 3)
                self.assertTrue(all(x["exhausted"] and not x["gaps"] for x in result["articles"]))

    def test_sample_membership_validates_three_language_identity(self):
        self.assertEqual(validate_corpus(sample_corpus())["expected_counts"], {"fi": 1, "sv": 1, "en": 1})

    def test_duplicate_source_page_key_is_rejected(self):
        doc = sample_corpus()
        doc["articles"][1]["source_wiki"] = "fiwiki"
        doc["articles"][1]["language"] = "fi"
        doc["articles"][1]["source_page_id"] = doc["articles"][0]["source_page_id"]
        with self.assertRaisesRegex(DataError, "duplicate source page key"):
            validate_corpus(doc)

    def test_anchor_cutoff_excludes_newer_same_second_neighbor(self):
        article = corpus_article()
        data = {"query": {"pages": [{"pageid": 101, "revisions": [
            rev(3001, "2025-08-01T00:00:00Z", "after anchor", 3000),
            rev(3000, "2025-08-01T00:00:00Z", "anchor body", 2999),
            rev(2999, "2025-07-31T23:59:59Z", "older", 0),
        ]}]}}
        api = FakeApi([data])
        with tempfile.TemporaryDirectory() as temp:
            result = acquire_article(article, Path(temp), api=api, sleep=lambda _: None, interval=0)
            self.assertEqual(result["record_count"], 2)
            self.assertTrue(result["state"]["anchor_validated"])
            self.assertTrue(result["state"]["enumeration_exhausted"])
            records = list((Path(temp) / "fiwiki" / "101").glob("batch-*.jsonl"))
            text = "\n".join(p.read_text() for p in records)
            self.assertNotIn('"source_revision_id":3001', text)
            self.assertIn("rvstartid=3000", api.urls[0])

    def test_resume_recovers_checksum_valid_orphan_batch(self):
        article = corpus_article()
        older = rev(2999, "2025-07-31T23:59:59Z", "older", 0)
        anchor = rev(3000, "2025-08-01T00:00:00Z", "anchor body", 2999)
        with tempfile.TemporaryDirectory() as temp:
            page = Path(temp) / "fiwiki" / "101"
            page.mkdir(parents=True)
            from scripts.palimpsest_data.history import revision_record
            rows = [revision_record(anchor, article), revision_record(older, article)]
            batch = page / "batch-000000.jsonl"
            batch.write_bytes(b"".join(canonical_json(r) + b"\n" for r in rows))
            state = {"schema_version": 1, "source_wiki": "fiwiki", "source_page_id": 101, "anchor_revision_id": 3000,
                     "continuation": None, "committed_batches": [], "anchor_validated": False,
                     "enumeration_exhausted": False, "unresolved_gaps": [], "seen_continuations": [], "gap_analysis_complete": False}
            atomic_json(page / "state.json", state)
            api = FakeApi([{"query": {"pages": [{"pageid": 101, "revisions": [anchor, older]}]}}])
            result = acquire_article(article, Path(temp), api=api, sleep=lambda _: None, interval=0)
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(len(result["state"]["recovered_orphans"]), 1)

    def test_corrupt_orphan_batch_is_not_recovered(self):
        article = corpus_article()
        with tempfile.TemporaryDirectory() as temp:
            page = Path(temp) / "fiwiki" / "101"
            page.mkdir(parents=True)
            state = {"schema_version": 1, "source_wiki": "fiwiki", "source_page_id": 101, "anchor_revision_id": 3000,
                     "continuation": None, "committed_batches": [], "anchor_validated": False,
                     "enumeration_exhausted": False, "unresolved_gaps": [], "seen_continuations": [], "gap_analysis_complete": False}
            atomic_json(page / "state.json", state)
            (page / "batch-000000.jsonl").write_text("{invalid json\n")
            with self.assertRaises(DataError):
                acquire_article(article, Path(temp), api=FakeApi([]), sleep=lambda _: None, interval=0)
            saved = json.loads((page / "state.json").read_text())
            self.assertEqual(saved["unresolved_gaps"][-1]["kind"], "orphan-batch-invalid")

    def test_cached_corrupt_batch_fails_closed(self):
        article = corpus_article()
        payload = {"query": {"pages": [{"pageid": 101, "revisions": [
            rev(3000, "2025-08-01T00:00:00Z", "anchor body", 0),
        ]}]}}
        with tempfile.TemporaryDirectory() as temp:
            acquire_article(article, Path(temp), api=FakeApi([payload]), sleep=lambda _: None, interval=0)
            batch = next((Path(temp) / "fiwiki" / "101").glob("batch-*.jsonl"))
            batch.write_text(batch.read_text() + " ")
            with self.assertRaisesRegex(DataError, "checksum mismatch"):
                acquire_article(article, Path(temp), api=FakeApi([]), sleep=lambda _: None, interval=0)

    def test_cached_exhausted_state_repairs_interrupted_gap_analysis(self):
        article = corpus_article()
        payload = {"query": {"pages": [{"pageid": 101, "revisions": [
            rev(3000, "2025-08-01T00:00:00Z", "anchor body", 2999),
        ]}]}}
        with tempfile.TemporaryDirectory() as temp:
            acquire_article(article, Path(temp), api=FakeApi([payload]), sleep=lambda _: None, interval=0)
            state_path = Path(temp) / "fiwiki" / "101" / "state.json"
            state = json.loads(state_path.read_text())
            state["gap_analysis_complete"] = False
            state["unresolved_gaps"] = []
            atomic_json(state_path, state)
            result = acquire_article(article, Path(temp), api=FakeApi([]), sleep=lambda _: None, interval=0)
            self.assertTrue(result["state"]["gap_analysis_complete"])
            self.assertIn("parent-not-acquired", [x["kind"] for x in result["state"]["unresolved_gaps"]])

    def test_source_sha1_mismatch_is_rejected(self):
        article = corpus_article()
        raw = rev(3000, "2025-08-01T00:00:00Z", "body")
        raw["slots"]["main"]["sha1"] = "incorrect"
        with self.assertRaisesRegex(DataError, "sha1 mismatch"):
            revision_record(raw, article)

    def test_source_sha1_hex_is_verified_and_preserved(self):
        article = corpus_article()
        raw = rev(3000, "2025-08-01T00:00:00Z", "body")
        raw["slots"]["main"]["sha1"] = hashlib.sha1(b"body").hexdigest()
        row = revision_record(raw, article)
        self.assertEqual(row["computed_sha1"], row["source_sha1"])
        self.assertEqual(row["computed_sha256"], hashlib.sha256(b"body").hexdigest())

    def test_missing_anchor_and_repeated_continuation_fail(self):
        article = corpus_article()
        with tempfile.TemporaryDirectory() as temp:
            missing = {"query": {"pages": [{"pageid": 101, "revisions": [rev(2999, "2025-07-31T23:59:59Z", "older")]}]}}
            with self.assertRaisesRegex(DataError, "not a public revision"):
                acquire_article(article, Path(temp), api=FakeApi([missing]), sleep=lambda _: None, interval=0)
        article = corpus_article()
        continued = {"query": {"pages": [{"pageid": 101, "revisions": [rev(3000, "2025-08-01T00:00:00Z", "anchor")]}]},
                     "continue": {"rvcontinue": "token", "continue": "-||"}}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(DataError, "repeated continuation"):
                acquire_article(article, Path(temp), api=FakeApi([continued, continued]), sleep=lambda _: None, interval=0)

    def test_retry_budget_is_finite(self):
        sleeps = []
        def fail(*args, **kwargs):
            raise urllib.error.URLError("offline")
        with self.assertRaisesRegex(DataError, r"retry limit \(2\)"):
            fetch_json("https://example.invalid", opener=fail, sleep=sleeps.append, retries=2, jitter=lambda: 0)
        self.assertEqual(len(sleeps), 2)

    def test_low_disk_preserves_checkpoint_and_resumes_after_capacity_returns(self):
        from types import SimpleNamespace
        article = corpus_article(anchor=3005)
        first_page = {"query": {"pages": [{"pageid": 101, "revisions": [
            rev(3005, "2025-08-01T00:00:00Z", "5", 3004),
            rev(3004, "2025-07-31T00:00:00Z", "4", 3003),
            rev(3003, "2025-07-30T00:00:00Z", "3", 3002),
            rev(3002, "2025-07-29T00:00:00Z", "2", 3001),
            rev(3001, "2025-07-28T00:00:00Z", "1", 3000),
        ]}]}, "continue": {"rvcontinue": "older"}}
        second_page = {"query": {"pages": [{"pageid": 101, "revisions": [rev(3000, "2025-07-27T00:00:00Z", "0", 0)]}]}}
        with tempfile.TemporaryDirectory() as temp:
            history = Path(temp)
            free_values = iter((10, 0))
            with self.assertRaisesRegex(DataError, "insufficient free disk space"):
                acquire_article(article, history, api=FakeApi([first_page, second_page]), sleep=lambda _: None,
                                interval=0, min_free_bytes=5, disk_usage=lambda _: SimpleNamespace(free=next(free_values)))
            checkpoint = json.loads((history / "fiwiki" / "101" / "state.json").read_text())
            self.assertEqual(len(checkpoint["committed_batches"]), 1)
            self.assertEqual(checkpoint["continuation"], {"rvcontinue": "older"})
            resumed = acquire_article(article, history, api=FakeApi([second_page]), sleep=lambda _: None,
                                      interval=0, min_free_bytes=5, disk_usage=lambda _: SimpleNamespace(free=10))
            self.assertTrue(resumed["state"]["enumeration_exhausted"])
            self.assertEqual(resumed["record_count"], 6)

    def test_xml_escapes_text_and_rejects_unavailable_nonhidden_content(self):
        article = corpus_article()
        source_hash = hashlib.sha1(b"A < B & C").hexdigest()
        record = {"source_revision_id": 3000, "source_parent_id": None, "timestamp": "2025-08-01T00:00:00Z",
                  "author": {"kind": "named", "value": "A&B", "hidden": False}, "comment": "<edit>",
                  "comment_hidden": False, "minor": False, "content_model": "wikitext", "content_format": "text/x-wiki",
                  "content": "A < B & C", "content_hidden": False, "source_sha1": source_hash}
        xml = mediawiki_xml(article, [record])
        root = ET.fromstring(xml)
        ns = {"m": "http://www.mediawiki.org/xml/export-0.11/"}
        revision = root.find(".//m:revision", ns)
        self.assertIsNotNone(revision.find("m:model", ns))
        self.assertIsNotNone(revision.find("m:format", ns))
        self.assertEqual(revision.find("m:sha1", ns).text, revision.find("m:text", ns).attrib["sha1"])
        self.assertEqual(len(revision.find("m:sha1", ns).text), 31)
        self.assertIn(b"A &lt; B &amp; C", xml)
        self.assertNotIn(b"<slots>", xml)
        record["content"] = None
        with self.assertRaisesRegex(DataError, "unavailable, non-hidden"):
            mediawiki_xml(article, [record])

    def test_streaming_xml_orders_batches_chronologically(self):
        article = corpus_article()
        def row(i, timestamp, text):
            return {"source_revision_id": i, "source_parent_id": None, "timestamp": timestamp,
                    "author": {"kind": "named", "value": "Editor", "hidden": False}, "comment": None,
                    "comment_hidden": False, "minor": False, "content_model": "wikitext", "content_format": "text/x-wiki",
                    "content": text, "content_hidden": False}
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "batch-0.jsonl"
            second = Path(temp) / "batch-1.jsonl"
            first.write_bytes(b"".join(canonical_json(x) + b"\n" for x in [row(3000, "2025-08-01T00:00:00Z", "new"), row(2999, "2025-07-31T00:00:00Z", "mid")]))
            second.write_bytes(canonical_json(row(2998, "2025-07-30T00:00:00Z", "old")) + b"\n")
            target = Path(temp) / "out.xml"
            export_article_stream(target, article, [first, second])
            doc = ET.parse(target).getroot()
            ns = {"m": "http://www.mediawiki.org/xml/export-0.11/"}
            ids = [int(x.text) for x in doc.findall(".//m:revision/m:id", ns)]
            self.assertEqual(ids, [2998, 2999, 3000])

    def test_incomplete_history_or_mapping_never_reports_complete(self):
        corpus = sample_corpus()
        with tempfile.TemporaryDirectory() as temp:
            report = build_coverage(corpus, Path(temp), project="fixture")
            self.assertFalse(report["complete"])
            self.assertEqual(exit_for_report(report), 1)
            for lang in ("fi", "sv", "en"):
                self.assertIsNone(report["per_language"][lang]["expected_revisions"])

    def test_coverage_joins_exact_source_mapping_and_live_local_revisions(self):
        corpus = sample_corpus()
        text = "sample body"
        digest = sha256_bytes(text.encode())
        runtime = {"schema_version": 1, "initialized": {x: True for x in ("fi", "sv", "en")},
                   "languages": {x: {"api_url": f"http://{x}/w/api.php"} for x in ("fi", "sv", "en")}}

        def runtime_for(root):
            return {**runtime, "project": "fixture", "data_root": str(root)}

        def create_tree(root, forged=False):
            for article in corpus["articles"]:
                source = {"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"],
                          "source_revision_id": article["anchor_revision_id"], "source_parent_id": None,
                          "timestamp": article["dataset_timestamp"], "author": {"kind": "named", "value": "Editor", "hidden": False},
                          "comment": "edit", "comment_hidden": False, "minor": False,
                          "content_model": "wikitext", "content_format": "text/x-wiki", "content": text,
                          "computed_sha256": digest, "anchor_revision_id": article["anchor_revision_id"]}
                batch = root / "history" / article["source_wiki"] / str(article["source_page_id"]) / "batch-000000.jsonl"
                batch.parent.mkdir(parents=True)
                batch.write_bytes(canonical_json(source) + b"\n")
                from scripts.palimpsest_data.io import sha256_file
                batch_digest = sha256_file(batch)
                atomic_json(batch.parent / "state.json", {"anchor_validated": True, "enumeration_exhausted": True,
                    "gap_analysis_complete": True, "unresolved_gaps": [], "committed_batches": [
                        {"path": batch.name, "sha256": batch_digest, "count": 1}]})
                mapping = {"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"],
                           "source_revision_id": article["anchor_revision_id"], "source_parent_id": None,
                           "local_page_id": article["source_page_id"] + 1000, "local_revision_id": article["anchor_revision_id"] + 1000,
                           "source_content_hash": "0" * 64 if forged else digest, "timestamp": source["timestamp"],
                           "author": source["author"], "comment": source["comment"], "comment_hidden": False,
                           "minor": False, "content_model": "wikitext", "content_format": "text/x-wiki",
                           "status": "reconciled", "batch_checksum": batch_digest}
                mp = root / "imports" / article["source_wiki"] / f"{article['source_page_id']}.jsonl"
                mp.parent.mkdir(parents=True)
                mp.write_bytes(canonical_json(mapping) + b"\n")

        def local_api(mode="good"):
            def api(url):
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(url)
                title = parse_qs(parsed.query)["titles"][0]
                lang = parsed.netloc.split(".")[0]
                article = next(a for a in corpus["articles"] if a["title"] == title and a["language"] == lang)
                content = "changed" if mode == "changed" else text
                revisions = [] if mode == "missing" else [{"revid": article["anchor_revision_id"] + 1000,
                    "parentid": 0, "timestamp": article["dataset_timestamp"], "user": "Imported>Editor", "comment": "edit",
                    "slots": {"main": {"content": content, "contentmodel": "wikitext", "contentformat": "text/x-wiki"}}}]
                return {"query": {"pages": [{"pageid": article["source_page_id"] + 1000, "revisions": revisions}]}}
            return api

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_tree(root)
            good = build_coverage(corpus, root, project="fixture", runtime_manifest=runtime_for(root), api=local_api())
            self.assertTrue(good["complete"], good["failures"])
            forged_root = root / "forged"
            create_tree(forged_root, forged=True)
            forged = build_coverage(corpus, forged_root, project="fixture", runtime_manifest=runtime_for(forged_root), api=local_api())
            self.assertFalse(forged["complete"])
            self.assertIn("mapping-source-identity-or-status-mismatch", {x["reason"] for x in forged["failures"]})
            missing = build_coverage(corpus, root, project="fixture", runtime_manifest=runtime_for(root), api=local_api("missing"))
            self.assertFalse(missing["complete"])
            self.assertIn("local-revision-missing-or-changed", {x["reason"] for x in missing["failures"]})
            changed = build_coverage(corpus, root, project="fixture", runtime_manifest=runtime_for(root), api=local_api("changed"))
            self.assertFalse(changed["complete"])
            self.assertIn("local-revision-missing-or-changed", {x["reason"] for x in changed["failures"]})
            missing_batch_root = root / "missing-batch"
            create_tree(missing_batch_root)
            missing_batch = next((missing_batch_root / "history").glob("**/batch-*.jsonl"))
            missing_batch.unlink()
            missing_report = build_coverage(corpus, missing_batch_root, project="fixture",
                                            runtime_manifest=runtime_for(missing_batch_root), api=local_api())
            self.assertFalse(missing_report["complete"])
            self.assertIn("source-batch-invalid", {x["reason"] for x in missing_report["failures"]})
            corrupt_batch_root = root / "corrupt-batch"
            create_tree(corrupt_batch_root)
            corrupt_batch = next((corrupt_batch_root / "history").glob("**/batch-*.jsonl"))
            corrupt_batch.write_text("not-jsonl\n")
            corrupt_report = build_coverage(corpus, corrupt_batch_root, project="fixture",
                                           runtime_manifest=runtime_for(corrupt_batch_root), api=local_api())
            self.assertFalse(corrupt_report["complete"])
            self.assertIn("source-batch-invalid", {x["reason"] for x in corrupt_report["failures"]})

    def test_import_reconciles_after_database_commit_before_c4_checkpoint(self):
        from urllib.parse import parse_qs, urlparse
        from scripts.palimpsest_data.io import sha256_file

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / "history"
            imports = root / "imports"
            articles = []
            source_by_title = {}
            for index, lang in enumerate(("fi", "sv", "en")):
                source_page_id = 990000100 + index
                first_id = 990001000 + index * 10
                anchor_id = first_id + 1
                title = f"Synthetic Crash Window {lang.upper()}"
                article = {"source_wiki": f"{lang}wiki", "language": lang, "source_page_id": source_page_id,
                           "anchor_revision_id": anchor_id, "title": title, "source_url": f"synthetic://{lang}/{source_page_id}",
                           "wikidata_id": None, "dataset_timestamp": "2025-08-02T00:00:00Z"}
                articles.append(article)
                rows = []
                for rev_id, parent_id, timestamp, content in (
                    (first_id, None, "2025-08-01T00:00:00Z", f"synthetic {lang} revision one"),
                    (anchor_id, first_id, "2025-08-02T00:00:00Z", f"synthetic {lang} revision two"),
                ):
                    source_sha1 = hashlib.sha1(content.encode()).hexdigest()
                    rows.append({"source_wiki": f"{lang}wiki", "source_page_id": source_page_id,
                                 "source_revision_id": rev_id, "source_parent_id": parent_id,
                                 "timestamp": timestamp, "author": {"kind": "named", "value": "CrashProbeEditor", "hidden": False},
                                 "comment": "synthetic crash-window test", "comment_hidden": False, "minor": False,
                                 "content_model": "wikitext", "content_format": "text/x-wiki", "content": content,
                                 "content_hidden": False, "source_sha1": source_sha1, "computed_sha1": source_sha1,
                                 "computed_sha256": sha256_bytes(content.encode()), "anchor_revision_id": anchor_id,
                                 "source_url": f"synthetic://{lang}/{source_page_id}/{rev_id}",
                                 "acquisition_method": "synthetic-crash-window-fixture", "acquired_at": "2026-11-14T00:00:00Z"})
                source_by_title[title] = rows
                page_dir = history / f"{lang}wiki" / str(source_page_id)
                page_dir.mkdir(parents=True)
                batch = page_dir / "batch-000000.jsonl"
                batch.write_bytes(b"".join(canonical_json(row) + b"\n" for row in reversed(rows)))
                atomic_json(page_dir / "state.json", {"schema_version": 1, "source_wiki": f"{lang}wiki",
                    "source_page_id": source_page_id, "anchor_revision_id": anchor_id, "anchor_validated": True,
                    "enumeration_exhausted": True, "gap_analysis_complete": True, "unresolved_gaps": [],
                    "committed_batches": [{"path": batch.name, "sha256": sha256_file(batch), "count": len(rows)}]})

            corpus_path = root / "synthetic-corpus.json"
            atomic_json(corpus_path, {"schema_version": 1, "release": {"repository": "synthetic-test-only", "tag": "s-2026-10", "assets": []},
                                      "scope": "sample", "expected_counts": {lang: 1 for lang in ("fi", "sv", "en")}, "articles": articles})
            runtime = {"schema_version": 1, "project": "fixture", "data_root": str(root),
                       "ports": {"fi": 18081, "sv": 18082, "en": 18083},
                       "initialized": {lang: True for lang in ("fi", "sv", "en")},
                       "languages": {lang: {"api_url": f"http://{lang}/api.php"} for lang in ("fi", "sv", "en")}}
            runtime_path = root / "runtime.json"
            atomic_json(runtime_path, runtime)
            remote: dict[str, tuple[int, list[dict[str, Any]]]] = {}
            import_calls: dict[str, int] = {}

            def api(url):
                title = parse_qs(urlparse(url).query)["titles"][0]
                if title not in remote:
                    return {"query": {"pages": [{"title": title, "missing": True}]}}
                page_id, rows = remote[title]
                revisions = [{"revid": row["revid"], "parentid": row["parentid"], "timestamp": row["timestamp"],
                              "user": row["user"], "comment": row["comment"], "slots": {"main": {
                                  "content": row["content"], "contentmodel": "wikitext", "contentformat": "text/x-wiki"}}}
                             for row in rows]
                return {"query": {"pages": [{"title": title, "pageid": page_id, "revisions": revisions}]}}

            def native_import(command, *, interrupt_once=False, **kwargs):
                xml_path = command[-1]
                source_page_id = int(Path(xml_path).stem)
                article = next(item for item in articles if item["source_page_id"] == source_page_id)
                title = article["title"]
                if title not in remote:
                    local_page_id = 120000000 + source_page_id
                    local_ids = {row["source_revision_id"]: 2200000000 + row["source_revision_id"] for row in source_by_title[title]}
                    local_rows = []
                    for source in sorted(source_by_title[title], key=lambda x: x["timestamp"]):
                        local_rows.append({"revid": local_ids[source["source_revision_id"]],
                                           "parentid": local_ids.get(source["source_parent_id"], 0),
                                           "timestamp": source["timestamp"], "user": "Imported>CrashProbeEditor",
                                           "comment": source["comment"], "content": source["content"]})
                    remote[title] = (local_page_id, local_rows)
                    import_calls[title] = import_calls.get(title, 0) + 1
                completed = subprocess.CompletedProcess(command, 0, "native import completed", "")
                if interrupt_once:
                    raise KeyboardInterrupt("simulated worker interruption after native import returned")
                return completed

            common = {"corpus_path": corpus_path, "history_dir": history, "import_dir": imports,
                      "runtime_manifest_path": runtime_path, "runtime_script": root / "scripts/runtime.py",
                      "container_data_root": "/data/imports/probe", "api": api,
                      "expected_project": "fixture", "expected_data_root": str(root)}
            with self.assertRaisesRegex(KeyboardInterrupt, "after native import returned"):
                import_corpus(**common, runner=lambda command, **kwargs: native_import(command, interrupt_once=True, **kwargs))
            first = articles[0]
            first_mapping = imports / first["source_wiki"] / f"{first['source_page_id']}.jsonl"
            self.assertEqual({row["status"] for row in iter_jsonl([first_mapping])}, {"pending"})
            self.assertEqual(import_calls[first["title"]], 1)

            resumed = import_corpus(**common, runner=native_import)
            self.assertEqual([page["status"] for page in resumed["pages"]],
                             ["already-reconciled", "reconciled", "reconciled"])
            self.assertEqual([import_calls[article["title"]] for article in articles], [1, 1, 1])
            for article in articles:
                mapping = list(iter_jsonl([imports / article["source_wiki"] / f"{article['source_page_id']}.jsonl"]))
                self.assertEqual(len(mapping), 2)
                self.assertEqual({row["status"] for row in mapping}, {"reconciled"})
                local_ids = [row["local_revision_id"] for row in mapping]
                self.assertEqual(len(local_ids), len(set(local_ids)))

    def test_support_cycle_is_reported_and_terminates(self):
        graph = {"Template:A": "{{Template:B}}", "Template:B": "{{Template:A}}"}
        report = discover_support("Article", "{{Template:A}}", "2025-08-01T00:00:00Z",
                                  lambda title, cutoff: {"title": title, "source_revision_id": 1, "timestamp": cutoff, "content": graph[title]})
        self.assertEqual(len(report["supporting"]), 2)
        self.assertTrue(report["cycles"])

    def test_support_budget_checkpoints_and_resumes_without_refetching(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "support.progress.json"
            calls = []
            def resolve(title, cutoff):
                calls.append(title)
                return {"title": title, "source_page_id": len(calls), "source_revision_id": len(calls),
                        "timestamp": cutoff, "content": "plain text"}
            first_budget = [1]
            partial = discover_support("Article", "{{Template:A}} {{Template:B}}", "2025-08-01T00:00:00Z",
                                       resolve, max_pages=10, progress_path=progress, request_budget=first_budget)
            self.assertFalse(partial["complete"])
            self.assertEqual(len(partial["pending"]), 1)
            self.assertEqual(calls, ["Template:A"])
            second_budget = [5]
            complete = discover_support("Article", "{{Template:A}} {{Template:B}}", "2025-08-01T00:00:00Z",
                                        resolve, max_pages=10, progress_path=progress, request_budget=second_budget)
            self.assertTrue(complete["complete"])
            self.assertEqual(calls, ["Template:A", "Template:B"])

    def test_asset_fetch_rejects_checksum_mismatch(self):
        body = b"right bytes"
        digest = hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = []
            for lang in ("fi", "sv", "en"):
                name = f"articles-{lang}.parquet"
                assets.append({"name": name, "size": len(body), "sha256": digest, "url": "https://test.invalid/" + name})
            lock = {"schema_version": 1, "tag": "s-2026-10", "assets": assets}
            lock_path = root / "lock.json"
            lock_path.write_text(json.dumps(lock))
            class Response:
                status = 200
                headers = {}
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, n=-1):
                    nonlocal body
                    value, body = body, b""
                    return value
            def opener(*args, **kwargs): return Response()
            bad_lock = json.loads(json.dumps(lock))
            bad_lock["assets"][0]["sha256"] = "0" * 64
            lock_path.write_text(json.dumps(bad_lock))
            with self.assertRaisesRegex(DataError, "does not match locked"):
                fetch_assets(lock_path, root / "out", opener=opener)


if __name__ == "__main__":
    unittest.main()

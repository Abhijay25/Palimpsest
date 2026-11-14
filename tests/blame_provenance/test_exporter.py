"""Isolated provenance export positives and integrity/race negatives."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from scripts.blame_provenance import build_bundles
from scripts.palimpsest_data.io import DataError, atomic_json, canonical_json, sha256_bytes


class ProvenanceExporterTests(unittest.TestCase):
    def fixture(self, root, *, hidden=False, race=False):
        articles = []
        records = {}
        text = "Å name / emoji 😀 e\u0301 \u2028"
        for lang in ("fi", "sv", "en"):
            article = {"source_wiki": lang + "wiki", "language": lang, "source_page_id": 800,
                       "anchor_revision_id": 900, "title": "Example " + lang, "source_url": "https://" + lang + ".wikipedia.org/?curid=800",
                       "wikidata_id": None, "dataset_timestamp": "2025-08-01T00:00:00Z"}
            articles.append(article)
            source = {"schema_version": 1, "source_wiki": lang + "wiki", "source_page_id": 800,
                      "source_revision_id": 900, "source_parent_id": None, "timestamp": article["dataset_timestamp"],
                      "author": {"kind": "named", "value": "Editor", "hidden": hidden}, "comment": "summary",
                      "comment_hidden": False, "minor": False, "content_model": "wikitext", "content_format": "text/x-wiki",
                      "content": text, "content_hidden": False, "computed_sha1": hashlib.sha1(text.encode()).hexdigest(),
                      "source_sha1": hashlib.sha1(text.encode()).hexdigest(), "computed_sha256": sha256_bytes(text.encode()),
                      "source_url": article["source_url"], "anchor_revision_id": 900}
            folder = root / "history" / (lang + "wiki") / "800"; folder.mkdir(parents=True)
            batch = canonical_json(source) + b"\n"; (folder / "batch-000000.jsonl").write_bytes(batch)
            digest = sha256_bytes(batch)
            atomic_json(folder / "state.json", {"anchor_validated": True, "enumeration_exhausted": True,
                        "gap_analysis_complete": True, "unresolved_gaps": [], "committed_batches": [{"path": "batch-000000.jsonl", "sha256": digest, "count": 1}]})
            mapping = {"schema_version": 1, "source_wiki": lang + "wiki", "source_page_id": 800,
                       "source_revision_id": 900, "source_parent_id": None, "local_page_id": 1, "local_revision_id": 7,
                       "source_content_hash": source["computed_sha256"], "timestamp": source["timestamp"],
                       "author": source["author"], "comment": "summary", "comment_hidden": False, "minor": False,
                       "content_model": "wikitext", "content_format": "text/x-wiki", "batch_checksum": digest, "status": "reconciled"}
            target = root / "imports" / (lang + "wiki") / "800.jsonl"; target.parent.mkdir(parents=True)
            target.write_bytes(canonical_json(mapping) + b"\n")
            records[lang] = source
        corpus = {"schema_version": 1, "scope": "sample", "release": {"repository": "MariaDB/mariadb-wikipedia-datasets", "tag": "s-2026-10", "assets": []},
                  "expected_counts": {lang: 1 for lang in records}, "articles": articles}
        runtime = {"schema_version": 1, "project": "fixture", "data_root": str(root.resolve()),
                   "initialized": {lang: True for lang in records}, "languages": {lang: {"api_url": "http://" + lang + ".local/api.php"} for lang in records}}
        calls = {lang: 0 for lang in records}
        def api(url):
            query = parse_qs(urlparse(url).query); lang = urlparse(url).hostname.split(".")[0]
            if query.get("meta") == ["siteinfo"]:
                return {"query": {"general": {"lang": lang, "wikiid": "mw_fixture_" + lang}}}
            calls[lang] += 1
            content = "altered during export" if race and calls[lang] > 1 else text
            return {"query": {"pages": [{"pageid": 1, "revisions": [{"revid": 7, "parentid": 0,
                    "timestamp": records[lang]["timestamp"], "user": "Imported>Editor", "comment": "summary",
                    "slots": {"main": {"content": content, "contentmodel": "wikitext", "contentformat": "text/x-wiki"}}}]}]}}
        return corpus, runtime, api

    def test_source_local_identity_and_unicode_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); corpus, runtime, api = self.fixture(root)
            bundles = build_bundles(corpus, root, runtime, api=api, generated_at="fixture")
            for lang, bundle in bundles.items():
                self.assertEqual(bundle["sha256"], sha256_bytes(canonical_json(bundle["payload"])))
                page = bundle["payload"]["pages"][0]; revision = page["revisions"][0]
                self.assertEqual((page["local_page_id"], page["source_page_id"]), (1, 800))
                self.assertEqual((revision["local_revision_id"], revision["source_revision_id"]), (7, 900))
                self.assertEqual(revision["user"], "Imported>Editor")
                self.assertEqual(revision["source_user"], "Editor")
                self.assertEqual(revision["source_url"], "https://" + lang + ".wikipedia.org/w/index.php?oldid=900")

    def test_corrupt_source_batch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); corpus,runtime,api=self.fixture(root)
            next((root/"history").glob("**/batch-*.jsonl")).write_text("{}\n")
            with self.assertRaisesRegex(DataError,"fully reconciled"): build_bundles(corpus,root,runtime,api=api)

    def test_forged_mapping_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); corpus,runtime,api=self.fixture(root)
            path=next((root/"imports").glob("**/*.jsonl")); data=json.loads(path.read_text());data["local_revision_id"]=999
            path.write_bytes(canonical_json(data)+b"\n")
            with self.assertRaisesRegex(DataError,"fully reconciled"): build_bundles(corpus,root,runtime,api=api)

    def test_hidden_source_identity_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); corpus,runtime,api=self.fixture(root,hidden=True)
            with self.assertRaisesRegex(DataError,"hidden source fields"): build_bundles(corpus,root,runtime,api=api)

    def test_local_change_between_audit_and_export_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); corpus,runtime,api=self.fixture(root,race=True)
            with self.assertRaisesRegex(DataError,"changed during export"): build_bundles(corpus,root,runtime,api=api)

if __name__ == "__main__": unittest.main()

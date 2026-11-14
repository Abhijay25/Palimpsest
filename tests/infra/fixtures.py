"""Small, deterministic synthetic corpus/history records for acceptance tests."""

from __future__ import annotations

import hashlib

from tests.infra.oracle import LANGUAGES


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pipeline_fixture() -> tuple[dict, list[dict], list[dict], list[dict], dict]:
    articles = []
    expected_revisions = []
    history = []
    imports = []
    for index, (language, wiki) in enumerate(LANGUAGES.items(), start=1):
        page_id = index * 10
        older_id = index * 100 + 1
        anchor_id = index * 100 + 2
        title = f"Fixture_{language}"
        articles.append({
            "source_wiki": wiki,
            "language": language,
            "source_page_id": page_id,
            "anchor_revision_id": anchor_id,
            "title": title,
            "source_url": f"https://{wiki}.wikipedia.org/wiki/{title}",
            "wikidata_id": None,
            "dataset_timestamp": None,
        })
        for revision_id, parent_id, text in (
            (older_id, None, ""),  # A genuinely empty page is visible content.
            (anchor_id, older_id, f"{language} snapshot\n"),
        ):
            digest = _digest(text)
            expected_revisions.append({
                "source_wiki": wiki,
                "source_page_id": page_id,
                "source_revision_id": revision_id,
                "source_parent_id": parent_id,
                "timestamp": "2025-08-01T10:00:00Z" if revision_id == older_id else "2025-08-01T10:01:00Z",
                "author": {"kind": "user", "value": f"fixture-{language}", "hidden": False},
                "comment": None,
                "comment_hidden": False,
                "minor": False,
                "content_model": "wikitext",
                "content_format": "text/x-wiki",
                "content": text,
                "content_hidden": False,
                "source_sha1": None,
                "computed_sha256": digest,
                "anchor_revision_id": anchor_id,
            })
            history.append({
                "source_wiki": wiki,
                "source_page_id": page_id,
                "source_revision_id": revision_id,
                "source_parent_id": parent_id,
                "timestamp": "2025-08-01T10:00:00Z" if revision_id == older_id else "2025-08-01T10:01:00Z",
                "author": {"kind": "user", "value": f"fixture-{language}", "hidden": False},
                "comment": None,
                "comment_hidden": False,
                "minor": False,
                "content_model": "wikitext",
                "content_format": "text/x-wiki",
                "content": text,
                "content_hidden": False,
                "source_sha1": None,
                "computed_sha256": digest,
                "source_url": f"https://{wiki}.wikipedia.org/w/index.php?oldid={revision_id}",
                "acquisition_method": "fixture",
                "acquired_at": "2026-11-14T00:00:00Z",
                "anchor_revision_id": anchor_id,
            })
            imports.append({
                "source_wiki": wiki,
                "source_revision_id": revision_id,
                "source_page_id": page_id,
                "source_parent_id": parent_id,
                # Deliberately unrelated to source revision numbers: identity comes from C4.
                "local_page_id": 1,
                "local_revision_id": 1 if revision_id == older_id else 2,
                "source_content_hash": digest,
                "timestamp": "2025-08-01T10:00:00Z" if revision_id == older_id else "2025-08-01T10:01:00Z",
                "author": {"kind": "user", "value": f"fixture-{language}", "hidden": False},
                "batch_checksum": "fixture-batch-sha256",
                "status": "imported",
                "errors": [],
            })

    corpus = {
        "schema_version": 1,
        "release": {"repository": "MariaDB/mariadb-wikipedia-datasets", "tag": "s-fixture", "assets": []},
        "scope": "sample",
        "expected_counts": {language: 1 for language in LANGUAGES},
        "articles": articles,
    }
    per_language = {}
    for language in LANGUAGES:
        per_language[language] = {
            "expected_articles": 1,
            "acquired_articles": 1,
            "imported_articles": 1,
            "reconciled_articles": 1,
            "expected_revisions": 2,
            "acquired_revisions": 2,
            "imported_revisions": 2,
            "reconciled_revisions": 2,
            "unresolved_pages": 0,
            "unresolved_revisions": 0,
        }
    coverage = {
        "schema_version": 1,
        "code_revision": "fixture-code-revision",
        "project": "palimpsest-c-fixture",
        "scope": "sample",
        "release": corpus["release"],
        "generated_at": "2026-11-14T00:00:00Z",
        "runtime_ready": False,
        "sample_verified": True,
        "per_language": per_language,
        "rendering": {"complete": False, "unresolved": []},
        "failures": [],
        "complete": True,
    }
    return corpus, expected_revisions, history, imports, coverage

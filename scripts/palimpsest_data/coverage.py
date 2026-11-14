from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from .io import DataError, atomic_json, iter_jsonl, read_json
from .history import iter_page_records
from .manifests import EXPECTED, LANGS, validate_corpus


def build_coverage(corpus: dict[str, Any], data_root: Path, *, project: str,
                   runtime_manifest: dict[str, Any] | None = None,
                   code_revision: str | None = None) -> dict[str, Any]:
    corpus = validate_corpus(corpus)
    history_root = data_root / "history"
    import_root = data_root / "imports"
    per_language: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    rendering_dependencies: dict[tuple[str, int, int], dict[str, Any]] = {}
    rendering_unresolved: list[dict[str, Any]] = []
    for lang in LANGS:
        articles = [a for a in corpus["articles"] if a["language"] == lang]
        acquired = imported = reconciled = acquired_revisions = imported_revisions = reconciled_revisions = 0
        expected_revisions: int | None = 0
        unresolved_pages = unresolved_revisions = 0
        for article in articles:
            page = history_root / article["source_wiki"] / str(article["source_page_id"])
            state_path = page / "state.json"
            if not state_path.exists():
                unresolved_pages += 1
                expected_revisions = None
                failures.append({"stage": "history", "language": lang, "page_id": article["source_page_id"], "reason": "checkpoint-missing"})
                continue
            state = read_json(state_path)
            if not state.get("gap_analysis_complete"):
                unresolved_pages += 1
                failures.append({"stage": "history", "language": lang, "page_id": article["source_page_id"], "reason": "gap-analysis-incomplete"})
            try:
                rows = list(iter_page_records(history_root, article))
            except DataError as e:
                rows = []
                unresolved_pages += 1
                failures.append({"stage": "history", "language": lang, "page_id": article["source_page_id"], "reason": str(e)})
            ids = {int(x["source_revision_id"]) for x in rows}
            anchor_ok = state.get("anchor_validated") and article["anchor_revision_id"] in ids
            if state.get("enumeration_exhausted") and anchor_ok:
                acquired += 1
                acquired_revisions += len(rows)
                if expected_revisions is not None:
                    expected_revisions += len(rows)
            else:
                unresolved_pages += 1
                expected_revisions = None
            for gap in state.get("unresolved_gaps", []):
                failures.append({"stage": "history", "language": lang, "page_id": article["source_page_id"], **gap})
                if gap.get("kind") in {"revision-text-unavailable", "parent-not-acquired", "anchor-timestamp-mismatch", "anchor-not-found"}:
                    unresolved_revisions += 1
            mapping_path = import_root / article["source_wiki"] / f"{article['source_page_id']}.jsonl"
            mapping = list(iter_jsonl([mapping_path])) if mapping_path.exists() else []
            imported += bool(mapping) and all(x.get("status") in {"imported", "reconciled"} for x in mapping)
            reconciled += bool(mapping) and all(x.get("status") == "reconciled" for x in mapping)
            imported_revisions += sum(x.get("status") in {"imported", "reconciled"} for x in mapping)
            reconciled_revisions += sum(x.get("status") == "reconciled" for x in mapping)
            if len(mapping) != len(rows):
                unresolved_revisions += abs(len(rows) - len(mapping)) or 1
                failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "reason": "mapping-count-mismatch", "source_revisions": len(rows), "mapping_records": len(mapping)})
            for row in mapping:
                if row.get("status") != "reconciled":
                    failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "revision_id": row.get("source_revision_id"), "reason": row.get("errors") or row.get("status")})
            support_path = data_root / "support" / article["source_wiki"] / f"{article['source_page_id']}.json"
            if not support_path.exists():
                rendering_unresolved.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "reason": "support-inventory-missing"})
            else:
                support = read_json(support_path)
                for item in support.get("supporting", []):
                    key = (article["source_wiki"], int(item["source_page_id"]), int(item["source_revision_id"]))
                    rendering_dependencies[key] = {"source_wiki": key[0], "source_page_id": key[1], "title": item.get("title"), "source_revision_id": key[2], "sha256": item.get("sha256")}
                for item in support.get("unresolved", []):
                    rendering_unresolved.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], **item})
                if support.get("cycles"):
                    rendering_unresolved.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "reason": "dependency-cycle", "cycles": support["cycles"]})
        per_language[lang] = {
            "expected_articles": corpus["expected_counts"][lang], "acquired_articles": acquired,
            "imported_articles": imported, "reconciled_articles": reconciled,
            "expected_revisions": expected_revisions, "acquired_revisions": acquired_revisions,
            "imported_revisions": imported_revisions, "reconciled_revisions": reconciled_revisions,
            "unresolved_pages": unresolved_pages, "unresolved_revisions": unresolved_revisions,
        }
        if acquired != len(articles):
            failures.append({"stage": "membership/history", "language": lang, "reason": "acquired-membership-incomplete", "expected": len(articles), "actual": acquired})
        if reconciled != len(articles):
            failures.append({"stage": "import", "language": lang, "reason": "reconciled-membership-incomplete", "expected": len(articles), "actual": reconciled})
    support_mapping_paths = sorted((data_root / "imports" / "support").glob("**/*.jsonl")) if (data_root / "imports" / "support").exists() else []
    support_mappings = [record for path in support_mapping_paths for record in iter_jsonl([path])]
    support_unreconciled = [record for record in support_mappings if record.get("status") != "reconciled"]
    if support_unreconciled:
        rendering_unresolved.extend({"reason": "support-import-unreconciled", "source_wiki": x.get("source_wiki"), "source_page_id": x.get("source_page_id"), "source_revision_id": x.get("source_revision_id"), "errors": x.get("errors")} for x in support_unreconciled)
    release = corpus["release"]
    full_membership = corpus["scope"] == "sample" or corpus["expected_counts"] == EXPECTED
    runtime_ready = bool(runtime_manifest and runtime_manifest.get("schema_version") == 1 and all(runtime_manifest.get("initialized", {}).get(lang) is True for lang in LANGS))
    sample_verified = corpus["scope"] == "sample" and all(
        per_language[lang]["acquired_articles"] == per_language[lang]["expected_articles"]
        and per_language[lang]["reconciled_articles"] == per_language[lang]["expected_articles"]
        and per_language[lang]["unresolved_pages"] == 0 and per_language[lang]["unresolved_revisions"] == 0
        for lang in LANGS
    )
    history_complete = all(per_language[lang]["expected_revisions"] is not None and per_language[lang]["acquired_revisions"] == per_language[lang]["expected_revisions"] for lang in LANGS)
    imports_complete = all(per_language[lang]["imported_revisions"] == per_language[lang]["acquired_revisions"] == per_language[lang]["reconciled_revisions"] for lang in LANGS)
    rendering_complete = bool(rendering_dependencies) and not rendering_unresolved and len(support_mappings) == len(rendering_dependencies)
    rendering = {"status": "complete" if rendering_complete else "incomplete", "dependencies": sorted(rendering_dependencies.values(), key=lambda x: (x["source_wiki"], x["title"] or "")),
                 "dependency_count": len(rendering_dependencies), "imported_dependency_revisions": len(support_mappings),
                 "unresolved": rendering_unresolved, "complete": rendering_complete}
    complete = full_membership and history_complete and imports_complete and all(per_language[x]["unresolved_pages"] == 0 and per_language[x]["unresolved_revisions"] == 0 for x in LANGS)
    return {
        "schema_version": 1, "code_revision": code_revision or "unknown", "project": project,
        "scope": corpus["scope"], "release": release, "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runtime_ready": runtime_ready, "sample_verified": sample_verified,
        "per_language": per_language, "rendering": rendering, "failures": failures,
        "complete": bool(complete),
    }


def write_coverage(path: Path, report: dict[str, Any]) -> None:
    atomic_json(path, report)


def exit_for_report(report: dict[str, Any]) -> int:
    return 0 if report.get("complete") else 1

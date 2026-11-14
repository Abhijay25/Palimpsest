from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .io import DataError, atomic_json, iter_jsonl, read_json, sha256_file
from .history import fetch_json, iter_page_records
from .importer import fetch_local_page
from .manifests import EXPECTED, LANGS, validate_corpus


def _local_api_json(url: str) -> dict[str, Any]:
    """Use a bounded request for local verification; source acquisition keeps its normal retries."""
    return fetch_json(url, retries=1, sleep=lambda _delay: None,
                      wait_on_rate_limit=False, timeout=8.0)


def failed_coverage_report(*, project: str, scope: str, code_revision: str,
                           reason: str, corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fresh failure document for an unexpected verification exception."""
    return {
        "schema_version": 1, "code_revision": code_revision or "unknown", "project": project,
        "scope": scope, "release": (corpus or {}).get("release"),
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runtime_ready": False, "sample_verified": False,
        "per_language": {lang: {"expected_articles": (corpus or {}).get("expected_counts", {}).get(lang), "acquired_articles": 0,
                                 "imported_articles": 0, "reconciled_articles": 0,
                                 "expected_revisions": None, "acquired_revisions": 0,
                                 "imported_revisions": 0, "reconciled_revisions": 0,
                                 "unresolved_pages": 0, "unresolved_revisions": 0}
                         for lang in LANGS},
        "rendering": {"status": "incomplete", "dependencies": [], "dependency_count": 0,
                      "imported_dependency_revisions": 0, "unresolved": [], "complete": False},
        "failures": [{"stage": "verification", "reason": "verification-failed", "detail": reason}],
        "complete": False,
    }


def build_coverage(corpus: dict[str, Any], data_root: Path, *, project: str,
                   runtime_manifest: dict[str, Any] | None = None,
                   code_revision: str | None = None, api=None) -> dict[str, Any]:
    corpus = validate_corpus(corpus)
    history_root = data_root / "history"
    import_root = data_root / "imports"
    per_language: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    rendering_dependencies: dict[tuple[str, int, int], dict[str, Any]] = {}
    rendering_unresolved: list[dict[str, Any]] = []
    runtime_identity_ok = bool(runtime_manifest and runtime_manifest.get("schema_version") == 1
                               and runtime_manifest.get("project") == project
                               and Path(runtime_manifest.get("data_root", "")).expanduser().resolve() == data_root.resolve())
    runtime_live: dict[str, bool] = {lang: False for lang in LANGS}
    if runtime_identity_ok:
        for lang in LANGS:
            lang_config = (runtime_manifest.get("languages") or {}).get(lang) or {}
            api_url = lang_config.get("api_url")
            if not api_url:
                failures.append({"stage": "runtime", "language": lang, "reason": "runtime-api-url-missing"})
                continue
            siteinfo_url = api_url + ("&" if "?" in api_url else "?") + urlencode({
                "action": "query", "meta": "siteinfo", "siprop": "general",
                "format": "json", "formatversion": 2,
            })
            try:
                payload = (api(siteinfo_url) if api else _local_api_json(siteinfo_url))
                general = payload.get("query", {}).get("general", {})
                if general.get("lang") != lang:
                    failures.append({"stage": "runtime", "language": lang, "reason": "runtime-language-mismatch",
                                     "expected_language": lang, "observed_language": general.get("lang")})
                elif general.get("wikiid") != f"mw_{project}_{lang}":
                    failures.append({"stage": "runtime", "language": lang, "reason": "runtime-wikiid-mismatch",
                                     "expected_wikiid": f"mw_{project}_{lang}", "observed_wikiid": general.get("wikiid")})
                else:
                    runtime_live[lang] = True
            except Exception as e:
                failures.append({"stage": "runtime", "language": lang, "reason": "siteinfo-query-failed", "detail": str(e)})
    elif runtime_manifest:
        failures.append({"stage": "runtime", "reason": "runtime-project-or-data-root-mismatch",
                         "expected_project": project, "observed_project": runtime_manifest.get("project"),
                         "expected_data_root": str(data_root.resolve()), "observed_data_root": runtime_manifest.get("data_root")})
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
            source_batch_hashes: dict[int, str] = {}
            for batch in state.get("committed_batches", []):
                batch_path = page / batch["path"]
                try:
                    batch_digest = sha256_file(batch_path)
                    for batch_row in iter_jsonl([batch_path]):
                        source_batch_hashes[int(batch_row["source_revision_id"])] = batch_digest
                except (DataError, OSError, KeyError, TypeError, ValueError) as e:
                    failures.append({"stage": "history", "language": lang, "page_id": article["source_page_id"], "reason": "source-batch-invalid", "batch": batch.get("path"), "detail": str(e)})
                    unresolved_pages += 1
                    expected_revisions = None
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
            source_by_id = {int(x["source_revision_id"]): x for x in rows}
            mapping_by_id: dict[int, list[dict[str, Any]]] = {}
            for item in mapping:
                try:
                    mapping_by_id.setdefault(int(item["source_revision_id"]), []).append(item)
                except (KeyError, TypeError, ValueError):
                    failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "reason": "invalid-source-revision-key"})
            valid: dict[int, dict[str, Any]] = {}
            for source_id, source in source_by_id.items():
                candidates = mapping_by_id.get(source_id, [])
                if len(candidates) != 1:
                    failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "revision_id": source_id, "reason": "mapping-missing-or-duplicate"})
                    unresolved_revisions += 1
                    continue
                item = candidates[0]
                expected = (source.get("source_wiki"), int(source.get("source_page_id", -1)), source.get("computed_sha256"), source.get("timestamp"), source.get("source_parent_id"), source.get("author"), source.get("comment"), source.get("comment_hidden", False), source.get("minor", False), source.get("content_model"), source.get("content_format"), source_batch_hashes.get(source_id))
                observed = (item.get("source_wiki"), item.get("source_page_id"), item.get("source_content_hash"), item.get("timestamp"), item.get("source_parent_id"), item.get("author"), item.get("comment"), item.get("comment_hidden", False), item.get("minor", False), item.get("content_model"), item.get("content_format"), item.get("batch_checksum"))
                if observed != expected or item.get("status") != "reconciled":
                    failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "revision_id": source_id, "reason": "mapping-source-identity-or-status-mismatch"})
                    unresolved_revisions += 1
                    continue
                valid[source_id] = item
            extras = set(mapping_by_id) - set(source_by_id)
            if extras:
                failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "reason": "mapping-has-extra-source-revisions", "revision_ids": sorted(extras)[:20]})
                unresolved_revisions += len(extras)
            observed_local: dict[int, tuple[int, dict[int, dict[str, Any]]]] = {}
            page_local_ok = True
            if valid and runtime_identity_ok and runtime_live[lang]:
                lang_config = (runtime_manifest.get("languages") or {}).get(lang) or {}
                api_url = lang_config.get("api_url")
                if not api_url:
                    failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "reason": "runtime-api-url-missing"})
                    page_local_ok = False
                else:
                    page_query_succeeded = False
                    try:
                        local_id, local_rows = fetch_local_page(api_url, article["title"], api=api or _local_api_json)
                        page_query_succeeded = True
                    except Exception as e:
                        local_id, local_rows = None, []
                        page_local_ok = False
                        runtime_live[lang] = False
                        failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"],
                                         "reason": "local-page-query-failed", "detail": str(e)})
                    if page_query_succeeded:
                        local_by_id = {int(x["revid"]): x for x in local_rows if type(x.get("revid")) is int}
                        observed_local[article["source_page_id"]] = (local_id or -1, local_by_id)
                        local_keys: set[int] = set()
                        for source_id, item in valid.items():
                            local_rev_id = item.get("local_revision_id")
                            local = local_by_id.get(local_rev_id) if type(local_rev_id) is int else None
                            source = source_by_id[source_id]
                            author = source.get("author") or {}
                            expected_user = author.get("value")
                            if expected_user and author.get("kind") == "named":
                                expected_user = "Imported>" + expected_user
                            source_parent = source.get("source_parent_id")
                            expected_local_parent = valid.get(source_parent, {}).get("local_revision_id") if source_parent else None
                            parent_matches = (source_parent is None and (local or {}).get("parentid") in (None, 0)) or (source_parent is not None and (local or {}).get("parentid") == expected_local_parent)
                            author_matches = author.get("hidden") or author.get("kind") == "unknown" or (local or {}).get("user") == expected_user
                            metadata_matches = ((source.get("comment_hidden", False) or (local or {}).get("comment") == source.get("comment"))
                                                and (local or {}).get("minor", False) == source.get("minor", False)
                                                and (local or {}).get("content_model") == source.get("content_model")
                                                and (local or {}).get("content_format") == source.get("content_format"))
                            if item.get("local_page_id") != local_id or local is None or local.get("timestamp") != item.get("timestamp") or local.get("content_hash") != item.get("source_content_hash") or local_rev_id in local_keys or not parent_matches or not author_matches or not metadata_matches:
                                page_local_ok = False
                                failures.append({"stage": "import", "language": lang, "page_id": article["source_page_id"], "revision_id": source_id, "reason": "local-revision-missing-or-changed"})
                                unresolved_revisions += 1
                            else:
                                local_keys.add(local_rev_id)
            good = len(valid) == len(rows) and len(mapping) == len(rows) and not extras
            imported += bool(good)
            reconciled += bool(good and runtime_manifest and observed_local and page_local_ok)
            imported_revisions += len(valid)
            reconciled_revisions += len(valid) if good and runtime_manifest and observed_local and page_local_ok else 0
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
    runtime_ready = bool(runtime_identity_ok and all(runtime_manifest.get("initialized", {}).get(lang) is True for lang in LANGS)
                         and all(runtime_live.values()))
    sample_verified = runtime_ready and corpus["scope"] == "sample" and all(
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
    complete = runtime_ready and full_membership and history_complete and imports_complete and all(per_language[x]["unresolved_pages"] == 0 and per_language[x]["unresolved_revisions"] == 0 for x in LANGS)
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

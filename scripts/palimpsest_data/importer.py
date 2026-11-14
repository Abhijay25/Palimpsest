from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .history import fetch_json, iter_page_records, validate_source_record_content
from .io import DataError, canonical_json, iter_jsonl, read_json, sha256_bytes, sha256_file
from .manifests import LANGS, validate_corpus
from .xml_export import export_article, export_article_stream


def source_pages(history_dir: Path, article: dict[str, Any]) -> list[dict[str, Any]]:
    page = history_dir / article["source_wiki"] / str(article["source_page_id"])
    rows = list(iter_jsonl(sorted(page.glob("batch-*.jsonl"))))
    if not rows:
        raise DataError(f"no history batches acquired for {article['source_wiki']}:{article['source_page_id']}")
    return rows


def iter_source_with_batch(history_dir: Path, article: dict[str, Any]):
    page = history_dir / article["source_wiki"] / str(article["source_page_id"])
    state = read_json(page / "state.json")
    for batch in state["committed_batches"]:
        path = page / batch["path"]
        checksum = sha256_file(path)
        if checksum != batch["sha256"]:
            raise DataError(f"committed source batch checksum mismatch: {path}")
        count = 0
        for record in iter_jsonl([path]):
            count += 1
            validate_source_record_content(record, context=f"{path} revision {record.get('source_revision_id')}")
            enriched = dict(record)
            enriched["batch_checksum"] = checksum
            yield enriched
        if count != batch["count"]:
            raise DataError(f"committed source batch record count mismatch: {path}")


def c4_record(source: dict[str, Any], *, local_page_id: int | None = None,
              local_revision_id: int | None = None, status: str = "pending",
              error: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1, "source_wiki": source["source_wiki"],
        "source_revision_id": source["source_revision_id"], "source_page_id": source["source_page_id"],
        "source_parent_id": source.get("source_parent_id"), "local_page_id": local_page_id,
        "local_revision_id": local_revision_id, "source_content_hash": source.get("computed_sha256"),
        "timestamp": source["timestamp"], "author": source.get("author"),
        "comment": source.get("comment"), "comment_hidden": source.get("comment_hidden", False),
        "minor": source.get("minor", False), "content_model": source.get("content_model"),
        "content_format": source.get("content_format"),
        "batch_checksum": source.get("batch_checksum"), "status": status, "errors": [error] if error else [],
    }


def write_pending_mapping(path: Path, sources) -> None:
    """Create/update C4 records atomically; an existing local mapping is immutable."""
    old = {int(x["source_revision_id"]): x for x in iter_jsonl([path])} if path.exists() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            for source in sources:
                key = int(source["source_revision_id"])
                prior = old.get(key)
                current = c4_record(source)
                if prior:
                    if prior.get("source_content_hash") != current.get("source_content_hash") or prior.get("timestamp") != current["timestamp"]:
                        raise DataError(f"C4 source record conflicts for {source['source_wiki']}:{key}")
                    record = prior
                else:
                    record = current
                out.write(canonical_json(record) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def local_revision_index(records: list[dict[str, Any]]) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
    index: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for item in records:
        timestamp = item.get("timestamp")
        content = item.get("content")
        content_hash = item.get("content_hash") or (sha256_bytes(content.encode("utf-8")) if isinstance(content, str) else None)
        index.setdefault((timestamp, content_hash), []).append(item)
    return index


def map_revisions(source_records: list[dict[str, Any]], local_records: list[dict[str, Any]],
                  local_page_id: int) -> list[dict[str, Any]]:
    """Map by observed local title/page + timestamp + text hash; never equate source/local IDs."""
    candidates = local_revision_index(local_records)
    used: set[int] = set()
    mapped = []
    for source in source_records:
        digest = source.get("computed_sha256")
        options = candidates.get((source["timestamp"], digest), [])
        options = [x for x in options if x.get("revid") not in used]
        if source.get("content") is None:
            # Deleted/suppressed source text cannot be safely matched by a fabricated empty body.
            mapped.append(c4_record(source, status="unresolved", error="source-content-unavailable; local revision identity cannot be verified"))
            continue
        if len(options) != 1:
            reason = "no-local-revision-match" if not options else "ambiguous-local-revision-match"
            mapped.append(c4_record(source, status="unresolved", error=reason))
            continue
        local = options[0]
        local_id = local.get("revid")
        if type(local_id) is not int or local_id <= 0:
            mapped.append(c4_record(source, status="unresolved", error="local revision has invalid ID"))
            continue
        used.add(local_id)
        row = c4_record(source, local_page_id=local_page_id, local_revision_id=local_id, status="reconciled")
        row["batch_checksum"] = source.get("batch_checksum")
        mapped.append(row)
    return mapped


def fetch_local_page(api_url: str, title: str, *, api: Callable = fetch_json) -> tuple[int | None, list[dict[str, Any]]]:
    params = {"action": "query", "format": "json", "formatversion": 2, "prop": "revisions",
              "titles": title, "rvprop": "ids|timestamp|content|user|comment|flags|contentmodel|contentformat", "rvslots": "main", "rvlimit": "max",
              "rvdir": "newer"}
    all_rows: list[dict[str, Any]] = []
    continuation = None
    seen = set()
    page_id: int | None = None
    while True:
        query = dict(params)
        if continuation:
            query.update(continuation)
        endpoint = api_url.rstrip("/")
        if not endpoint.endswith("api.php"):
            endpoint += "/w/api.php"
        data = api(endpoint + "?" + urllib.parse.urlencode(query))
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") is not None:
            return None, []
        page_id = pages[0].get("pageid")
        for rev in pages[0].get("revisions", []):
            main = (rev.get("slots") or {}).get("main") or rev
            content = main.get("content", main.get("*"))
            all_rows.append({"revid": rev.get("revid"), "parentid": rev.get("parentid"), "timestamp": rev.get("timestamp"),
                             "content_hash": sha256_bytes(content.encode("utf-8")) if isinstance(content, str) else None,
                             "user": rev.get("user"), "comment": rev.get("comment"), "minor": "minor" in rev,
                             "content_model": main.get("contentmodel") or rev.get("contentmodel"),
                             "content_format": main.get("contentformat") or rev.get("contentformat")})
        continuation = data.get("continue")
        if not continuation:
            break
        token_hash = sha256_bytes(canonical_json(continuation))
        if token_hash in seen:
            raise DataError(f"local revision pagination repeated continuation for {title!r}")
        seen.add(token_hash)
    if type(page_id) is not int or page_id <= 0:
        raise DataError(f"local page {title!r} has invalid ID")
    return page_id, all_rows


def map_revisions_stream(source_records, local_records: list[dict[str, Any]], local_page_id: int,
                         path: Path) -> dict[str, int]:
    candidates = local_revision_index(local_records)
    used: set[int] = set()
    counts = {"reconciled": 0, "unresolved": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            for source in source_records:
                digest = source.get("computed_sha256")
                options = [x for x in candidates.get((source["timestamp"], digest), []) if x.get("revid") not in used]
                if source.get("content") is None:
                    record = c4_record(source, status="unresolved", error="source-content-unavailable; local revision identity cannot be verified")
                elif len(options) != 1:
                    record = c4_record(source, status="unresolved", error="no-local-revision-match" if not options else "ambiguous-local-revision-match")
                else:
                    local_id = options[0].get("revid")
                    if type(local_id) is not int or local_id <= 0:
                        record = c4_record(source, status="unresolved", error="local revision has invalid ID")
                    else:
                        used.add(local_id)
                        record = c4_record(source, local_page_id=local_page_id, local_revision_id=local_id, status="reconciled")
                        counts["reconciled"] += 1
                out.write(canonical_json(record) + b"\n")
                if record["status"] != "reconciled":
                    counts["unresolved"] += 1
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return counts


def _runtime_command(runtime_script: Path, c1: dict[str, Any], ports_arg: str,
                     language: str, container_xml: str) -> list[str]:
    return ["python3", str(runtime_script), "--project", c1["project"], "--data-root", c1["data_root"],
            "--ports", ports_arg, "exec", "--language", language, "--", "php", "maintenance/run.php",
            "importDump", "--username-prefix=Imported", container_xml]


def _import_support(records: list[tuple[dict[str, Any], dict[str, Any]]], import_dir: Path,
                    c1: dict[str, Any], runtime_script: Path, ports_arg: str,
                    container_data_root: str, *, api: Callable, runner: Callable,
                    dry_run: bool) -> list[dict[str, Any]]:
    unique: dict[tuple[str, int, int], tuple[dict[str, Any], dict[str, Any]]] = {}
    for article, item in records:
        key = (article["source_wiki"], int(item["source_page_id"]), int(item["source_revision_id"]))
        old = unique.get(key)
        if old and old[1].get("sha256") != item.get("sha256"):
            raise DataError(f"supporting revision has conflicting source text: {key}")
        unique[key] = (article, item)
    results = []
    ordered = sorted(unique.values(), key=lambda x: (x[0]["source_wiki"], x[1]["title"].casefold(), x[1]["timestamp"], x[1]["source_revision_id"]))
    for article, item in ordered:
        source = {
            "source_wiki": article["source_wiki"], "source_page_id": int(item["source_page_id"]),
            "source_revision_id": int(item["source_revision_id"]), "source_parent_id": item.get("source_parent_id"),
            "timestamp": item["timestamp"], "author": item.get("author"), "comment": item.get("comment"),
            "comment_hidden": item.get("comment_hidden", False), "minor": item.get("minor", False),
            "content_model": item.get("content_model") or ("Scribunto" if item.get("namespace_id") == 828 else "wikitext"),
            "content_format": item.get("content_format") or ("text/plain" if item.get("namespace_id") == 828 else "text/x-wiki"),
            "content": item.get("content"), "content_hidden": item.get("content_hidden", False),
            "source_sha1": item.get("source_sha1"), "computed_sha1": item.get("computed_sha1"),
            "computed_sha256": item.get("sha256"),
            "source_url": item.get("source_url"), "acquisition_method": item.get("acquisition_method"),
            "acquired_at": item.get("acquired_at"), "anchor_revision_id": item.get("source_revision_id"),
            "batch_checksum": sha256_bytes(canonical_json(item)),
        }
        validate_source_record_content(source, context=f"supporting revision {source['source_wiki']}:{source['source_page_id']}:{source['source_revision_id']}")
        title = item["title"]
        if source["content"] is None:
            results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "blocked-hidden-content"})
            continue
        support_article = {"source_wiki": article["source_wiki"], "language": article["language"],
                           "source_page_id": source["source_page_id"], "anchor_revision_id": source["source_revision_id"],
                           "title": title, "namespace_id": item.get("namespace_id", 10)}
        identity = f"{source['source_page_id']}-{source['source_revision_id']}"
        mapping_path = import_dir / "support" / article["source_wiki"] / f"{identity}.jsonl"
        xml_path = import_dir / "xml-support" / article["source_wiki"] / f"{identity}.xml"
        write_pending_mapping(mapping_path, [source])
        local_id, local_rows = fetch_local_page(c1["languages"][article["language"]]["api_url"], title, api=api)
        if local_id is not None:
            preflight = map_revisions_stream([source], local_rows, local_id, mapping_path)
            if preflight["unresolved"] == 0:
                results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "already-reconciled"})
                continue
        export_article(xml_path, support_article, [source])
        container_xml = f"{container_data_root.rstrip('/')}/imports/xml-support/{article['source_wiki']}/{identity}.xml"
        command = _runtime_command(runtime_script, c1, ports_arg, article["language"], container_xml)
        if dry_run:
            results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "prepared", "xml": str(xml_path), "command": command})
            continue
        completed = runner(command, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "failed", "error": completed.stderr[-1000:]})
            continue
        local_id, local_rows = fetch_local_page(c1["languages"][article["language"]]["api_url"], title, api=api)
        if local_id is None:
            results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "imported-but-page-not-found"})
            continue
        mapped = map_revisions_stream([source], local_rows, local_id, mapping_path)
        results.append({"source_wiki": source["source_wiki"], "source_page_id": source["source_page_id"], "source_revision_id": source["source_revision_id"], "title": title, "status": "reconciled" if mapped["unresolved"] == 0 else "imported-with-gaps"})
    return results


def import_corpus(corpus_path: Path, history_dir: Path, import_dir: Path,
                  runtime_manifest_path: Path, runtime_script: Path,
                  *, container_data_root: str = "/data", api: Callable = fetch_json,
                  runner: Callable = subprocess.run, dry_run: bool = False,
                  expected_project: str | None = None, expected_data_root: str | None = None) -> dict[str, Any]:
    corpus = validate_corpus(read_json(corpus_path))
    c1 = read_json(runtime_manifest_path)
    if c1.get("schema_version") != 1 or c1.get("project") is None:
        raise DataError("runtime manifest is missing or unsupported C1 schema")
    if expected_project and c1.get("project") != expected_project:
        raise DataError(f"C1 project {c1.get('project')!r} does not match requested project {expected_project!r}")
    if expected_data_root and Path(c1.get("data_root", "")).expanduser().resolve() != Path(expected_data_root).expanduser().resolve():
        raise DataError("C1 data_root does not match requested data root")
    if not all(c1.get("initialized", {}).get(lang) is True for lang in LANGS):
        raise DataError("all three local wikis must be initialized before data import")
    ports = c1.get("ports") or {"fi": 8081, "sv": 8082, "en": 8083}
    ports_arg = ",".join(str(ports[lang]) for lang in LANGS)
    result = {"scope": corpus["scope"], "pages": [], "support_pages": [], "bridge": "runtime.py exec --language; runtime containers mount imports read-only at /data/imports"}
    support_records = []
    support_complete = True
    for article in corpus["articles"]:
        support_path = history_dir.parent / "support" / article["source_wiki"] / f"{article['source_page_id']}.json"
        if not support_path.exists():
            support_complete = False
            result["support_pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "inventory-missing"})
            continue
        inventory = read_json(support_path)
        if inventory.get("schema_version") != 1:
            raise DataError(f"unsupported supporting-content inventory: {support_path}")
        support_complete &= bool(inventory.get("complete"))
        support_records.extend((article, item) for item in inventory.get("supporting", []))
        if inventory.get("unresolved"):
            result["support_pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "incomplete-inventory", "unresolved": inventory["unresolved"]})
    result["support_pages"].extend(_import_support(support_records, import_dir, c1, runtime_script, ports_arg,
                                                    container_data_root, api=api, runner=runner, dry_run=dry_run))
    support_complete &= all(item.get("status") in {"reconciled", "already-reconciled", "prepared"} for item in result["support_pages"] if "status" in item)
    result["support_complete"] = support_complete
    for article in corpus["articles"]:
        state_path = history_dir / article["source_wiki"] / str(article["source_page_id"]) / "state.json"
        state = read_json(state_path)
        if not state.get("anchor_validated") or not state.get("enumeration_exhausted"):
            raise DataError(f"history for {article['source_wiki']}:{article['source_page_id']} is not complete and anchor-validated")
        mapping_path = import_dir / article["source_wiki"] / f"{article['source_page_id']}.jsonl"
        source_iter = iter_source_with_batch(history_dir, article)
        write_pending_mapping(mapping_path, source_iter)
        if any(x.get("content") is None for x in iter_source_with_batch(history_dir, article)):
            result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "blocked-hidden-content"})
            continue
        lang_info = c1["languages"][article["language"]]
        local_page_id, local_revisions = fetch_local_page(lang_info["api_url"], article["title"], api=api)
        missing_revision_ids: set[int] | None = None
        if local_page_id is not None:
            preflight_counts = map_revisions_stream(iter_source_with_batch(history_dir, article), local_revisions, local_page_id, mapping_path)
            preflight = list(iter_jsonl([mapping_path]))
            if preflight_counts["unresolved"] == 0:
                result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "local_page_id": local_page_id, "status": "already-reconciled", "local-edit-preserved": True})
                continue
            missing_revision_ids = {int(x["source_revision_id"]) for x in preflight if x.get("errors") == ["no-local-revision-match"]}
            if any(x.get("status") == "unresolved" and x.get("errors") != ["no-local-revision-match"] for x in preflight):
                result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "blocked-ambiguous-existing-revisions"})
                continue
            if not missing_revision_ids:
                result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "blocked-unclassified-existing-revisions"})
                continue
        # Page and revisions are imported via MediaWiki maintenance, never SQL. Source IDs
        # are carried in the XML only as source metadata and are not used as local IDs.
        xml_path = import_dir / "xml" / article["source_wiki"] / f"{article['source_page_id']}.xml"
        state = read_json(state_path)
        batch_paths = [history_dir / article["source_wiki"] / str(article["source_page_id"]) / b["path"] for b in state["committed_batches"]]
        export_article_stream(xml_path, article, batch_paths, only_revision_ids=missing_revision_ids)
        container_xml = f"{container_data_root.rstrip('/')}/imports/xml/{article['source_wiki']}/{article['source_page_id']}.xml"
        command = _runtime_command(runtime_script, c1, ports_arg, article["language"], container_xml)
        if dry_run:
            result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "prepared", "command": command, "xml": str(xml_path)})
            continue
        completed = runner(command, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            error = f"maintenance import failed ({completed.returncode}): {completed.stderr[-1000:]}"
            result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "failed", "error": error})
            continue
        local_page_id, local_revisions = fetch_local_page(lang_info["api_url"], article["title"], api=api)
        if local_page_id is None:
            result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "status": "imported-but-page-not-found"})
            continue
        mappings = map_revisions_stream(iter_source_with_batch(history_dir, article), local_revisions, local_page_id, mapping_path)
        status = "reconciled" if mappings["unresolved"] == 0 else "imported-with-gaps"
        result["pages"].append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "local_page_id": local_page_id, "status": status, **mappings})
    return result

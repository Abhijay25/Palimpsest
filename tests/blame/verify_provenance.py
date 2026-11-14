"""Read-only comparison of actual imported sample mappings and Blame responses.

This requires the root-owned six-page sample and provenance export. It never
edits imported pages, mappings, histories, or the runtime. Negative corruption
controls remain owned by the orchestrator's isolated-copy workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from mediawiki_api import MediaWikiApiError, WikiApi
from seed_synthetic import LANGS, DOCKER_PROJECT, load_manifest
from verify_live import validate_analyze_schema


def canonical_payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_source_revisions(data_root: Path, source_wiki: str, source_page_id: int) -> dict[int, dict]:
    directory = data_root / "history" / source_wiki / str(source_page_id)
    records = {}
    for path in sorted(directory.glob("batch-*.jsonl")):
        for row in read_jsonl(path):
            records[int(row["source_revision_id"])] = row
    if not records:
        raise AssertionError(f"no retained C3 history for {source_wiki}:{source_page_id}")
    return records


def load_local_mappings(data_root: Path, source_wiki: str, source_page_id: int) -> dict[int, dict]:
    path = data_root / "imports" / source_wiki / f"{source_page_id}.jsonl"
    records = read_jsonl(path)
    reconciled = [row for row in records if row.get("status") == "reconciled"]
    if not reconciled:
        raise AssertionError(f"no reconciled C4 mappings for {source_wiki}:{source_page_id}")
    return {int(row["local_revision_id"]): row for row in reconciled}


def equal(record: dict, field: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"local revision {record.get('local_revision_id')} {field} mismatch: {actual!r} != {expected!r}")


def verify_source_url(record: dict, value: str, source_wiki: str, source_revision_id: int) -> None:
    parsed = urlparse(value)
    expected_host = source_wiki.removesuffix("wiki") + ".wikipedia.org"
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise AssertionError(f"source URL is not on the mapped {source_wiki} host")
    if parse_qs(parsed.query).get("oldid") != [str(source_revision_id)]:
        raise AssertionError(f"source URL does not target mapped source revision {source_revision_id}")


def verify_page(api: WikiApi | None, data_root: Path, bundle: dict, page: dict) -> int:
    source_wiki = bundle["source_wiki"]
    source_page_id = int(page["source_page_id"])
    local_page_id = int(page["local_page_id"])
    source_revisions = load_source_revisions(data_root, source_wiki, source_page_id)
    local_mappings = load_local_mappings(data_root, source_wiki, source_page_id)
    bundle_revisions = {int(row["local_revision_id"]): row for row in page["revisions"]}
    if set(bundle_revisions) != set(local_mappings):
        raise AssertionError(f"{source_wiki}:{source_page_id}: bundle and C4 local revision sets differ")

    for local_id, item in bundle_revisions.items():
        mapping = local_mappings[local_id]
        source_id = int(item["source_revision_id"])
        source = source_revisions.get(source_id)
        if source is None:
            raise AssertionError(f"C3 history lacks mapped source revision {source_wiki}:{source_page_id}:{source_id}")
        equal(item, "C4 source_page_id", int(mapping["source_page_id"]), source_page_id)
        equal(item, "C4 source_revision_id", int(mapping["source_revision_id"]), source_id)
        equal(item, "C4 source_content_hash", mapping.get("source_content_hash"), source.get("computed_sha256"))
        equal(item, "C3 content hash", item.get("sha256"), source.get("computed_sha256"))
        equal(item, "C3 timestamp", item.get("timestamp"), source.get("timestamp"))
        equal(item, "C4 source_parent_id", mapping.get("source_parent_id"), source.get("source_parent_id"))
        equal(item, "C4 content_model", mapping.get("content_model"), source.get("content_model"))
        equal(item, "C4 minor flag", mapping.get("minor"), source.get("minor"))
        equal(item, "C4 source author metadata", mapping.get("author"), source.get("author"))
        equal(item, "C4 comment visibility", mapping.get("comment_hidden"), source.get("comment_hidden"))
        equal(item, "C4 imported comment", mapping.get("comment"), None if source.get("comment_hidden") else source.get("comment"))
        verify_source_url(item, item["source_url"], source_wiki, source_id)
        verify_source_url(item, source["source_url"], source_wiki, source_id)
        source_author = source.get("author") or {}
        if source_author.get("hidden"):
            if item.get("source_user") is not None:
                raise AssertionError("hidden source identity was copied into the trusted bundle")
        else:
            equal(item, "source_user", item.get("source_user"), source_author.get("value"))
        if source.get("content_hidden") or source.get("content") is None:
            raise AssertionError("the selected public sample unexpectedly contains hidden or missing source text")
        actual_hash = hashlib.sha256(source["content"].encode("utf-8")).hexdigest()
        equal(item, "source text SHA-256", actual_hash, item.get("sha256"))

    anchor_id = int(page["source_anchor_revision_id"])
    anchor = next((row for row in page["revisions"] if int(row["source_revision_id"]) == anchor_id), None)
    if anchor is None:
        raise AssertionError(f"source anchor {anchor_id} is absent from the local mapping bundle")
    local_anchor_id = int(anchor["local_revision_id"])
    if api is None:
        return len(bundle_revisions)
    response = api.call({
        "action": "palimpsestblame", "op": "analyze", "title": page["title"], "revision": local_anchor_id,
    })
    result = response.get("palimpsestblame")
    if not isinstance(result, dict):
        raise AssertionError("ordinary imported sample response has no palimpsestblame object")
    errors = validate_analyze_schema(result)
    if errors:
        raise AssertionError("ordinary imported sample response schema invalid before semantic checks: " + "; ".join(errors))
    equal(page, "local page ID", result["page"].get("id"), local_page_id)
    equal(page, "snapshot ID", result["snapshot"].get("revision_id"), local_anchor_id)
    equal(page, "snapshot timestamp", result["snapshot"].get("timestamp"), anchor["timestamp"])
    equal(page, "snapshot user", result["snapshot"].get("user"), anchor["user"])
    equal(page, "snapshot comment", result["snapshot"].get("comment"), anchor["comment"])
    equal(page, "source text hash", hashlib.sha256(result["source_text"].encode("utf-8")).hexdigest(), anchor["sha256"])
    coverage = result["coverage"]
    equal(page, "coverage source wiki", coverage.get("source_wiki"), source_wiki)
    equal(page, "coverage source page ID", coverage.get("source_page_id"), source_page_id)
    equal(page, "coverage source anchor", coverage.get("source_anchor_revision_id"), anchor_id)

    api_revisions = {int(row["revision_id"]): row for row in result["revisions"]}
    if not set(bundle_revisions).issubset(api_revisions):
        raise AssertionError(f"{source_wiki}:{source_page_id}: API omitted one or more imported revisions")
    for local_id, item in bundle_revisions.items():
        revision = api_revisions[local_id]
        equal(item, "API parent", revision.get("parent_id"), item.get("local_parent_id"))
        equal(item, "API timestamp", revision.get("timestamp"), item.get("timestamp"))
        equal(item, "API user", revision.get("user"), item.get("user"))
        equal(item, "API comment", revision.get("comment"), item.get("comment"))
        equal(item, "API minor flag", revision.get("minor"), item.get("minor"))
        source = revision.get("source") or {}
        for source_field in ("wiki", "page_id", "revision_id", "parent_id", "url"):
            expected_field = {
                "wiki": source_wiki,
                "page_id": source_page_id,
                "revision_id": item["source_revision_id"],
                "parent_id": item["source_parent_id"],
                "url": item["source_url"],
            }[source_field]
            equal(item, f"API source {source_field}", source.get(source_field), expected_field)
        expected_source_user = item.get("source_user") if revision.get("user") is not None else None
        expected_source_comment = item.get("comment") if revision.get("comment") is not None else None
        equal(item, "API source user visibility", source.get("user"), expected_source_user)
        equal(item, "API source comment visibility", source.get("comment"), expected_source_comment)
    return len(bundle_revisions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--offline-only", action="store_true", help="validate C3/C4 and exporter/served bundle consistency without claiming API coverage")
    args = parser.parse_args()
    if args.confirm_project != DOCKER_PROJECT:
        parser.error(f"--confirm-project must be {DOCKER_PROJECT}")
    try:
        manifest = load_manifest(args.manifest)
        totals = {}
        for language in LANGS:
            bundle_path = args.bundle_dir / f"{language}.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            serving_path = args.data_root / "config" / language / f"{language}.json"
            serving_bundle = json.loads(serving_path.read_text(encoding="utf-8"))
            if bundle.get("schema_version") != 1 or bundle.get("language") != language:
                raise ValueError(f"invalid {language} provenance wrapper")
            if serving_bundle != bundle:
                raise AssertionError(f"{language} served provenance config differs from the export copy")
            if canonical_payload_hash(bundle["payload"]) != bundle.get("sha256"):
                raise AssertionError(f"{language} trusted provenance payload checksum mismatch")
            expected_wiki = {"fi": "fiwiki", "sv": "svwiki", "en": "enwiki"}[language]
            if bundle.get("source_wiki") != expected_wiki:
                raise AssertionError(f"{language} bundle points at unexpected source wiki")
            api = None if args.offline_only else WikiApi(manifest["languages"][language]["api_url"])
            page_total = 0
            revision_total = 0
            for page in bundle["payload"]["pages"]:
                revision_total += verify_page(api, args.data_root, bundle, page)
                page_total += 1
            totals[language] = {"pages": page_total, "revisions": revision_total}
        label = "PASS offline C3/C4 provenance inputs" if args.offline_only else "PASS real provenance API"
        print(label + ": " + json.dumps(totals, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, MediaWikiApiError, AssertionError) as exc:
        print(f"FAIL real provenance acceptance: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

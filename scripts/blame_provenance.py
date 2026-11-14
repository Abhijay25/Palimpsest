#!/usr/bin/env python3
"""Export verified, read-only source/local provenance for PalimpsestBlame."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.palimpsest_data.coverage import build_coverage
from scripts.palimpsest_data.history import fetch_json
from scripts.palimpsest_data.importer import fetch_local_page, iter_source_with_batch
from scripts.palimpsest_data.io import DataError, atomic_json, canonical_json, iter_jsonl, read_json, sha256_bytes
from scripts.palimpsest_data.manifests import LANGS, load_corpus


def build_bundles(corpus, data_root: Path, runtime, *, api=fetch_json, generated_at=None):
    """Validate C3/C4 against the real local runtime before exporting any file."""
    project = runtime.get("project")
    if not project:
        raise DataError("runtime project missing")
    report = build_coverage(corpus, data_root, project=project, runtime_manifest=runtime, api=api)
    if not report["complete"]:
        reasons = [str(item.get("reason")) for item in report["failures"][:8]]
        raise DataError("provenance requires fully reconciled requested history scope: " + "; ".join(reasons))
    pages = {language: [] for language in LANGS}
    for article in corpus["articles"]:
        lang = article["language"]
        records = list(iter_source_with_batch(data_root / "history", article))
        source = {row["source_revision_id"]: row for row in records}
        mapping_path = data_root / "imports" / article["source_wiki"] / (str(article["source_page_id"]) + ".jsonl")
        mappings = list(iter_jsonl([mapping_path]))
        mapped = {row["source_revision_id"]: row for row in mappings}
        if len(mapped) != len(source) or len(mapped) != len(mappings):
            raise DataError("duplicate or missing provenance mapping")
        local_page, local_rows = fetch_local_page(runtime["languages"][lang]["api_url"], article["title"], api=api)
        local = {row["revid"]: row for row in local_rows}
        revisions = []
        for source_id, original in sorted(source.items(), key=lambda pair: (pair[1]["timestamp"], pair[0])):
            row = mapped[source_id]
            actual = local.get(row.get("local_revision_id"))
            author = original.get("author") or {}
            if any((original.get("content_hidden"), author.get("hidden"), original.get("comment_hidden"))):
                raise DataError("hidden source fields cannot be exported as public provenance")
            if actual is None or row.get("local_page_id") != local_page:
                raise DataError("mapping changed during export")
            expected_user = author.get("value")
            if author.get("kind") == "named" and expected_user:
                expected_user = "Imported>" + expected_user
            parent = original.get("source_parent_id")
            expected_parent = mapped[parent]["local_revision_id"] if parent in mapped else 0
            expected = (original["timestamp"], original["computed_sha256"], expected_user,
                        original.get("comment"), bool(original.get("minor")), original.get("content_model"), expected_parent)
            observed = (actual.get("timestamp"), actual.get("content_hash"), actual.get("user"),
                        actual.get("comment"), bool(actual.get("minor")), actual.get("content_model"), actual.get("parentid") or 0)
            if expected != observed or row.get("source_content_hash") != original["computed_sha256"] or row.get("batch_checksum") != original["batch_checksum"]:
                raise DataError("local or source revision changed during export")
            revisions.append({
                "local_revision_id": actual["revid"], "local_parent_id": actual.get("parentid") or 0,
                "source_revision_id": source_id, "source_parent_id": parent,
                "timestamp": original["timestamp"], "sha256": original["computed_sha256"],
                "user": actual.get("user"), "source_user": author.get("value"),
                "comment": original.get("comment"), "minor": bool(original.get("minor")),
                "content_model": original.get("content_model"),
                "source_url": f"https://{lang}.wikipedia.org/w/index.php?oldid={source_id}",
            })
        anchor = source[article["anchor_revision_id"]]
        pages[lang].append({"local_page_id": local_page, "source_page_id": article["source_page_id"],
                            "title": article["title"], "source_anchor_revision_id": article["anchor_revision_id"],
                            "source_anchor_timestamp": anchor["timestamp"], "history_complete": True, "revisions": revisions})
    generated_at = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bundles = {}
    for lang in LANGS:
        payload = {"pages": sorted(pages[lang], key=lambda item: item["source_page_id"])}
        bundles[lang] = {"schema_version": 1, "language": lang, "source_wiki": f"{lang}wiki",
                         "generated_at": generated_at, "sha256": sha256_bytes(canonical_json(payload)), "payload": payload}
    return bundles


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--install", action="store_true", help="also install each verified language bundle in that runtime's existing read-only config mount")
    args = parser.parse_args(argv)
    root = args.data_root.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else root / "blame-provenance"
    try:
        corpus = load_corpus(args.manifest.resolve())
        runtime = read_json(root / "runtime.json")
        bundles = build_bundles(corpus, root, runtime)
        for lang, bundle in bundles.items():
            atomic_json(output / f"{lang}.json", bundle)
            if args.install:
                atomic_json(root / "config" / lang / f"{lang}.json", bundle)
            print(f"{lang}: {len(bundle['payload']['pages'])} verified pages, {sum(len(p['revisions']) for p in bundle['payload']['pages'])} revisions -> {output / (lang + '.json')}")
    except (DataError, OSError, ValueError, KeyError) as error:
        print(f"blame provenance: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

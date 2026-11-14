from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import DataError, read_json

LANGS = ("fi", "sv", "en")
WIKIS = {"fi": "fiwiki", "sv": "svwiki", "en": "enwiki"}
EXPECTED = {"fi": 19285, "sv": 4921, "en": 5254}


def validate_corpus(doc: Any, *, require_full_counts: bool = False) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise DataError("unsupported corpus manifest schema_version (expected 1)")
    if doc.get("scope") not in {"sample", "full"}:
        raise DataError("corpus scope must be sample or full")
    if doc.get("release", {}).get("tag") != "s-2026-10":
        raise DataError("corpus release must identify locked S release s-2026-10")
    counts = doc.get("expected_counts")
    if not isinstance(counts, dict) or set(counts) != set(LANGS):
        raise DataError("expected_counts must contain exactly fi, sv and en")
    if any(not isinstance(counts[x], int) or counts[x] < 0 for x in LANGS):
        raise DataError("expected_counts values must be nonnegative integers")
    if doc["scope"] == "full" and counts != EXPECTED:
        raise DataError(f"full expected_counts must be {EXPECTED}")
    if require_full_counts and doc["scope"] == "full" and counts != EXPECTED:
        raise DataError("full manifest membership counts differ from locked release")
    articles = doc.get("articles")
    if not isinstance(articles, list):
        raise DataError("articles must be a list")
    keys: set[tuple[str, int]] = set()
    actual = {x: 0 for x in LANGS}
    for i, article in enumerate(articles):
        if not isinstance(article, dict):
            raise DataError(f"article {i} is not an object")
        lang = article.get("language")
        wiki = article.get("source_wiki")
        page_id = article.get("source_page_id")
        anchor = article.get("anchor_revision_id")
        if lang not in WIKIS or wiki != WIKIS[lang]:
            raise DataError(f"article {i} has inconsistent source_wiki/language")
        if type(page_id) is not int or page_id <= 0:
            raise DataError(f"article {i} source_page_id must be a positive integer")
        if type(anchor) is not int or anchor <= 0:
            raise DataError(f"article {i} anchor_revision_id must be a positive integer")
        key = (wiki, page_id)
        if key in keys:
            raise DataError(f"duplicate source page key {key}")
        keys.add(key)
        actual[lang] += 1
        for field in ("title", "source_url"):
            if not isinstance(article.get(field), str) or not article[field].strip():
                raise DataError(f"article {i} {field} is required")
        for field in ("wikidata_id", "dataset_timestamp"):
            if article.get(field) is not None and not isinstance(article[field], str):
                raise DataError(f"article {i} {field} must be string or null")
    if actual != counts:
        raise DataError(f"manifest article counts {actual} do not equal expected_counts {counts}")
    if doc["scope"] == "sample" and not all(actual.values()):
        raise DataError("sample manifest must explicitly include at least one article per language")
    return doc


def load_corpus(path: Path) -> dict[str, Any]:
    return validate_corpus(read_json(path))


def load_lock(path: Path) -> dict[str, Any]:
    lock = read_json(path)
    if lock.get("schema_version") != 1 or lock.get("tag") != "s-2026-10":
        raise DataError("unsupported or unexpected S dataset lock")
    names: set[str] = set()
    for item in lock.get("assets", []):
        if item["name"] in names:
            raise DataError(f"duplicate locked asset {item['name']}")
        names.add(item["name"])
        if len(item.get("sha256", "")) != 64 or item.get("size", 0) <= 0:
            raise DataError(f"invalid lock entry for {item.get('name')}")
    for lang in LANGS:
        if f"articles-{lang}.parquet" not in names:
            raise DataError(f"locked release missing articles-{lang}.parquet")
    return lock

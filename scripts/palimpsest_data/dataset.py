from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .io import DataError, atomic_json, sha256_file
from .manifests import EXPECTED, LANGS, WIKIS, load_lock


def fetch_assets(lock_path: Path, out_dir: Path, *, opener: Callable = urllib.request.urlopen) -> dict[str, Any]:
    lock = load_lock(lock_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for asset in lock["assets"]:
        name = asset["name"]
        dest = out_dir / name
        if dest.exists():
            if dest.stat().st_size == asset["size"] and sha256_file(dest) == asset["sha256"]:
                results.append({"name": name, "status": "verified-existing"})
                continue
            raise DataError(f"existing asset {name} fails locked size or SHA-256; move it aside before fetching")
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset >= asset["size"]:
                part.unlink(missing_ok=True)
                offset = 0
            headers = {"User-Agent": "PalimpsestData/1.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(asset["url"], headers=headers)
            with opener(request, timeout=60) as response:
                status = getattr(response, "status", getattr(response, "code", 200))
                if offset and status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-"):
                        raise DataError(f"server resumed {name} at an unexpected byte range")
                    mode = "ab"
                elif status == 200:
                    # Server ignored Range; safely restart from byte zero.
                    mode = "wb"
                else:
                    raise DataError(f"unexpected HTTP {status} while downloading {name}")
                with part.open(mode) as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
        except (OSError, urllib.error.URLError) as e:
            raise DataError(f"download interrupted for {name}; verified resume state was retained at {part}: {e}") from e
        if part.stat().st_size != asset["size"] or sha256_file(part) != asset["sha256"]:
            part.unlink(missing_ok=True)
            raise DataError(f"downloaded asset {name} does not match locked size/SHA-256")
        os.replace(part, dest)
        results.append({"name": name, "status": "downloaded-and-verified"})
    return {"tag": lock["tag"], "assets": results}


def article_from_row(row: dict[str, Any], lang: str) -> dict[str, Any]:
    page_id = row.get("page_id")
    rev_id = row.get("rev_id")
    if type(page_id) is not int or page_id <= 0 or type(rev_id) is not int or rev_id <= 0:
        raise DataError(f"{lang} row has invalid page_id/rev_id")
    title = row.get("title")
    if not isinstance(title, str) or not title:
        raise DataError(f"{lang} page {page_id} has no title")
    url = row.get("url")
    timestamp = row.get("date_modified")
    wikidata_id = row.get("wikidata_id")
    if timestamp is not None and not isinstance(timestamp, str):
        timestamp = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    return {
        "source_wiki": WIKIS[lang], "language": lang, "source_page_id": page_id,
        "anchor_revision_id": rev_id, "title": title, "source_url": url or f"https://{lang}.wikipedia.org/?curid={page_id}",
        "wikidata_id": wikidata_id, "dataset_timestamp": timestamp,
    }


def build_membership(asset_dir: Path, lock_path: Path, *, parquet_reader=None) -> dict[str, Any]:
    lock = load_lock(lock_path)
    if parquet_reader is None:
        try:
            import pyarrow.parquet as pq  # type: ignore
        except ImportError as e:
            raise DataError("Parquet membership requires the pinned tooling container (pyarrow==22.0.0)") from e
        parquet_reader = lambda path: pq.read_table(path).to_pylist()
    articles: list[dict[str, Any]] = []
    counts = {}
    for lang in LANGS:
        path = asset_dir / f"articles-{lang}.parquet"
        asset = next(a for a in lock["assets"] if a["name"] == path.name)
        if not path.exists() or path.stat().st_size != asset["size"] or sha256_file(path) != asset["sha256"]:
            raise DataError(f"{path.name} is missing or fails the release lock")
        rows = parquet_reader(path)
        page_ids: set[int] = set()
        rev_ids: set[int] = set()
        count = 0
        for row in rows:
            article = article_from_row(row, lang)
            if article["source_page_id"] in page_ids:
                raise DataError(f"duplicate source page ID {lang}:{article['source_page_id']}")
            if article["anchor_revision_id"] in rev_ids:
                raise DataError(f"duplicate anchor revision ID {lang}:{article['anchor_revision_id']}")
            page_ids.add(article["source_page_id"])
            rev_ids.add(article["anchor_revision_id"])
            articles.append(article)
            count += 1
        if count != EXPECTED[lang]:
            raise DataError(f"{lang} membership count {count}, expected {EXPECTED[lang]}")
        counts[lang] = count
    articles.sort(key=lambda a: (a["source_wiki"], a["source_page_id"], a["anchor_revision_id"]))
    return {
        "schema_version": 1,
        "release": {"repository": lock["repository"], "tag": lock["tag"], "assets": lock["assets"]},
        "scope": "full", "expected_counts": counts, "articles": articles,
    }

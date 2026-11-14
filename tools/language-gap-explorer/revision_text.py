"""Revision text retrieval with an on-disk cache; no retrieval occurs on page reads."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Palimpsest/0.1 (https://github.com/Abhijay25/Palimpsest; hackathon research)"
HISTORY_TTL_SECONDS = 10 * 60


def cache_root() -> Path:
    return Path(os.environ.get("LANGGAP_FLAGS_CACHE", "data/flags-cache"))


def cache_path(lang: str, revision: int) -> Path:
    return cache_root() / "revisions" / f"{lang}-{revision}.json"


def history_cache_path(lang: str, page_id: int) -> Path:
    """The short-lived source-history cache, separate from immutable revisions."""
    return cache_root() / "history" / f"{lang}-{page_id}.json"


def cached_revision(lang: str, revision: int) -> dict[str, Any] | None:
    try:
        data = json.loads(cache_path(lang, revision).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def fetch_revision(lang: str, revision: int, timeout: float = 20) -> dict[str, Any]:
    """Fetch one revision and cache it. Raises RuntimeError with a user-safe message."""
    hit = cached_revision(lang, revision)
    if hit is not None:
        return hit
    query = urlencode({"action": "query", "prop": "revisions", "rvprop": "ids|content|timestamp",
                       "rvslots": "main", "revids": str(revision), "format": "json"})
    request = Request(f"https://{lang}.wikipedia.org/w/api.php?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: fixed Wikimedia host
            data = json.load(response)
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        record = page.get("revisions", [])[0]
        text = record.get("slots", {}).get("main", {}).get("*")
        if not isinstance(text, str):
            raise ValueError("revision content missing")
        output = {"revision_id": int(record["revid"]), "parent_id": record.get("parentid"),
                  "timestamp": record.get("timestamp", ""), "title": page.get("title", ""), "wikitext": text}
    except (OSError, ValueError, KeyError, IndexError) as error:
        raise RuntimeError("Revision text is unavailable; no empty diff was rendered.") from error
    path = cache_path(lang, revision)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    return output


def cached_history(lang: str, page_id: int, now: float | None = None) -> list[dict[str, Any]] | None:
    """Read a recent revision selector cache without presenting stale data as live."""
    path = history_cache_path(lang, page_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = (time.time() if now is None else now) - float(data.get("cached_at", 0))
        rows = data.get("revisions")
        if age > HISTORY_TTL_SECONDS or not isinstance(rows, list):
            return None
        return [dict(row) for row in rows if isinstance(row, dict)]
    except (OSError, ValueError, TypeError):
        return None


def fetch_history(lang: str, page_id: int, revision: int | None, title: str,
                  timeout: float = 20) -> list[dict[str, Any]]:
    """Fetch up to ten source revisions for an article and cache them for ten minutes.

    This is deliberately metadata-only.  Revision content is still fetched only when
    the reviewer explicitly starts a detector scan.
    """
    hit = cached_history(lang, page_id)
    if hit is not None:
        return hit
    params: dict[str, str] = {
        "action": "query", "prop": "revisions", "pageids": str(page_id),
        "rvprop": "ids|timestamp|user|comment|size", "rvlimit": "10",
        "rvdir": "older", "format": "json",
    }
    if revision:
        params["rvstartid"] = str(revision)
    request = Request(f"https://{lang}.wikipedia.org/w/api.php?{urlencode(params)}",
                      headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: fixed Wikimedia host
            data = json.load(response)
        page = next(iter(data.get("query", {}).get("pages", {}).values()))
        revisions = page.get("revisions", [])
        if not isinstance(revisions, list):
            raise ValueError("revision history missing")
        rows = [{
            "revision": int(item["revid"]), "parent_id": item.get("parentid"),
            "timestamp": str(item.get("timestamp", "")), "user": str(item.get("user", "")),
            "comment": str(item.get("comment", "")), "size": item.get("size"),
            "title": str(page.get("title") or title),
        } for item in revisions if isinstance(item, dict) and item.get("revid")]
        if not rows:
            raise ValueError("revision history is empty")
    except (OSError, ValueError, KeyError, IndexError) as error:
        raise RuntimeError("Revision history is unavailable; no revision selector was inferred.") from error
    path = history_cache_path(lang, page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cached_at": time.time(), "revisions": rows}, ensure_ascii=False),
                    encoding="utf-8")
    return rows

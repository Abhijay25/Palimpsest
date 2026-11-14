"""Revision text retrieval with an on-disk cache; no retrieval occurs on page reads."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Palimpsest/0.1 (https://github.com/Abhijay25/Palimpsest; hackathon research)"


def cache_root() -> Path:
    return Path(os.environ.get("LANGGAP_FLAGS_CACHE", "data/flags-cache"))


def cache_path(lang: str, revision: int) -> Path:
    return cache_root() / "revisions" / f"{lang}-{revision}.json"


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

"""Run the page-internal consistency check on the small fi scout history sets.

Usage: UV_CACHE_DIR=/tmp/palimpsest-uv-cache uv run python eval/scout/history/out_of_sync.py
"""

import asyncio
import json
import time
from pathlib import Path

import httpx

from palimpsest.backends.gemini import gemini_enabled
from palimpsest.citation_dates import (
    _MONTH_CACHE,
    _MONTH_INDEX,
    _WEEKDAY_CACHE,
    _WEEKDAY_INDEX,
)
from palimpsest.consistency import GeminiConsistencyJudge, check_page_consistency
from palimpsest.crosslingual import MEDIAWIKI_USER_AGENT
from palimpsest.segment import split_edit

ROOT = Path(__file__).parent
OUT = ROOT.parent.parent / "runs" / "out_of_sync" / "findings.md"


class _RateLimit:
    def __init__(self) -> None:
        self.previous = 0.0

    async def wait(self) -> None:
        delay = 1.0 - (time.monotonic() - self.previous)
        if delay > 0:
            await asyncio.sleep(delay)
        self.previous = time.monotonic()


async def _get(
    client: httpx.AsyncClient, limiter: _RateLimit, params: dict[str, str]
) -> dict[str, object]:
    await limiter.wait()
    response = await client.get(
        "https://fi.wikipedia.org/w/api.php",
        params=params,
        headers={"User-Agent": MEDIAWIKI_USER_AGENT},
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _prime_names(client: httpx.AsyncClient, limiter: _RateLimit) -> None:
    data = await _get(
        client,
        limiter,
        {
            "action": "query",
            "meta": "allmessages",
            "ammessages": "|".join((*_MONTH_INDEX, *_WEEKDAY_INDEX)),
            "amlang": "fi",
            "format": "json",
            "formatversion": "2",
        },
    )
    query = data.get("query", {})
    messages = query.get("allmessages", []) if isinstance(query, dict) else []
    months: dict[str, int] = {}
    weekdays: dict[str, int] = {}
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        name, content = message.get("name"), message.get("content")
        if not isinstance(name, str) or not isinstance(content, str):
            continue
        text = " ".join(content.split()).casefold()
        if name in _MONTH_INDEX:
            months[text] = _MONTH_INDEX[name]
        if name in _WEEKDAY_INDEX:
            weekdays[text] = _WEEKDAY_INDEX[name]
    _MONTH_CACHE["fi"] = months
    _WEEKDAY_CACHE["fi"] = weekdays


async def _revisions(
    client: httpx.AsyncClient, limiter: _RateLimit, old: int, new: int
) -> tuple[str, str]:
    data = await _get(
        client,
        limiter,
        {
            "action": "query",
            "prop": "revisions",
            "revids": f"{old}|{new}",
            "rvslots": "main",
            "rvprop": "ids|content",
            "format": "json",
            "formatversion": "2",
        },
    )
    query = data.get("query", {})
    pages = query.get("pages", []) if isinstance(query, dict) else []
    found: dict[int, str] = {}
    for page in pages if isinstance(pages, list) else []:
        revisions = page.get("revisions", []) if isinstance(page, dict) else []
        for revision in revisions if isinstance(revisions, list) else []:
            if not isinstance(revision, dict):
                continue
            revision_id, slots = revision.get("revid"), revision.get("slots", {})
            main = slots.get("main", {}) if isinstance(slots, dict) else {}
            content = main.get("content", "") if isinstance(main, dict) else ""
            if isinstance(revision_id, int) and isinstance(content, str):
                found[revision_id] = content
    return found.get(old, ""), found.get(new, "")


async def main() -> None:
    limiter = _RateLimit()
    judge = GeminiConsistencyJudge() if gemini_enabled() else None
    counts: dict[str, dict[str, int]] = {
        "swaps": {"deterministic": 0, "semantic": 0},
        "controls": {"deterministic": 0, "semantic": 0},
    }
    failures = 0
    hits: list[str] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        await _prime_names(client, limiter)
        for label, filename in (
            ("swaps", "value_swaps.jsonl"),
            ("controls", "controls.jsonl"),
        ):
            for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                parent, revision = row.get("bad_parent_id"), row.get("bad_rev_id")
                if not isinstance(parent, int) or not isinstance(revision, int):
                    failures += 1
                    continue
                try:
                    old, new = await _revisions(client, limiter, parent, revision)
                    findings = await check_page_consistency(
                        old,
                        new,
                        split_edit(old, new, old, new),
                        "fi",
                        judge=judge,
                        client=client,
                    )
                    for finding in findings:
                        counts[label][finding.method] += 1
                        hits.append(
                            f"- {label} | {row.get('page_title')} | rev {revision} |"
                            f" {finding.method} | {finding.old_value} -> {finding.new_value} |"
                            f" section: {finding.section} | page still says: {finding.quote[:200]}"
                        )
                except (httpx.HTTPError, ValueError, KeyError):
                    failures += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# OUT_OF_SYNC scout verification\n\n"
        f"- swaps: deterministic {counts['swaps']['deterministic']}, semantic {counts['swaps']['semantic']}\n"
        f"- controls: deterministic {counts['controls']['deterministic']}, semantic {counts['controls']['semantic']}\n"
        f"- failed revision fetches: {failures}\n"
        f"- semantic judge: {'enabled' if judge is not None else 'disabled (set Gemini credentials and PALIMPSEST_USE_GEMINI=1)'}\n"
        "\n## Findings\n\n" + "\n".join(hits) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())

"""Pure helpers for the explicit revision-audit tab.

This module deliberately knows nothing about Flask, MariaDB, or the detector.  A
tracker occurrence may repeat a source revision; the tab audits it once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class RevisionRef:
    lang: str
    revision_id: int
    title: str
    timestamp: str = ""
    url: str = ""
    parent_id: int | None = None


def block_revisions(context: Mapping[str, Any]) -> list[RevisionRef]:
    """Return distinct current-edition source revisions from a tracker context."""
    current = str(context.get("current_lang") or context.get("source") or "")
    rows: Iterable[Mapping[str, Any]] = context.get("historical_occurrences") or ()
    # A fixture can supply the already scoped block directly.
    if context.get("block_revisions"):
        rows = ({"evidence": context["block_revisions"]},)
    result: list[RevisionRef] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        for evidence in row.get("evidence", ()):
            if current and evidence.get("lang") != current:
                continue
            try:
                revision_id = int(evidence.get("revision", evidence.get("rev_id")))
            except (TypeError, ValueError):
                continue
            lang = str(evidence.get("lang") or current)
            key = (lang, revision_id)
            if not lang or key in seen:
                continue
            seen.add(key)
            result.append(RevisionRef(
                lang=lang, revision_id=revision_id,
                title=str(evidence.get("title") or context.get("title") or context.get("topic") or "Untitled"),
                timestamp=str(evidence.get("stamp") or evidence.get("timestamp") or ""),
                url=str(evidence.get("url") or ""),
                parent_id=_integer(evidence.get("parent_id")),
            ))
    return result


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def rank_revisions(audits: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Stable severity ranking: admin, counts, review, then no findings."""
    ranked: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
    for index, item in enumerate(audits):
        flags = item.get("flags") if isinstance(item.get("flags"), list) else []
        admin = sum(isinstance(flag, Mapping) and flag.get("tier") == "admin" for flag in flags)
        review = sum(isinstance(flag, Mapping) and flag.get("tier") == "review" for flag in flags)
        # Descending numerical tuple; enumerate preserves source order for ties.
        ranked.append(((-int(admin > 0), -admin, -review), index, dict(item)))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [item for _, _, item in ranked]


def audit_payload(ref: RevisionRef, old_wikitext: str, new_wikitext: str) -> dict[str, Any]:
    """The exact public AuditDiffRequest wire contract."""
    return {
        "lang_code": ref.lang,
        "page_title": ref.title,
        "old_revision_id": ref.parent_id or 0,
        "new_revision_id": ref.revision_id,
        "editor_username": "language-gap-explorer",
        "old_text": old_wikitext,
        "new_text": new_wikitext,
        "old_wikitext": old_wikitext,
        "new_wikitext": new_wikitext,
        "ref_urls": [ref.url] if ref.url.startswith(("http://", "https://")) else [],
    }

"""Replay randomly sampled real Wikipedia edits through the live API and score them
against what later editors actually did (reverted / corrected / stood).

Usage: python -I eval/history_replay.py <edits_xx.jsonl>... --out <dir>
The API must be running on 127.0.0.1:8765. Ground truth comes only from later history
(collected by an isolated scout); the API sees only the edit itself.
"""

import argparse
import json
import re
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "http://127.0.0.1:8765/api/v1/audit-diff"
_MARKUP = re.compile(
    r"<ref[^>]*>.*?</ref>|<ref[^>]*/>|\{\{[^{}]*\}\}|'''?|\[\[(?:[^\]|]*\|)?|\]\]"
)


def plain(text: str) -> str:
    return " ".join(_MARKUP.sub("", text or "").split()).casefold()


def audit_request(
    edit: dict[str, object], *, fresh: bool = False
) -> urllib.request.Request:
    """Build the shared audit-diff request used by replay-style evaluators."""
    old, new = str(edit["old_wikitext"]), str(edit["new_wikitext"])
    body = {
        "lang_code": edit["lang"],
        "page_title": edit["page_title"],
        "old_revision_id": edit.get("parent_id") or 0,
        "new_revision_id": edit.get("rev_id") or 0,
        "editor_username": "replay",
        "old_text": old,
        "new_text": new,
        "old_wikitext": old,
        "new_wikitext": new,
        "ref_urls": [],
    }
    headers = {"Content-Type": "application/json"}
    if fresh:
        headers["X-Palimpsest-Fresh"] = "1"
    return urllib.request.Request(API, json.dumps(body).encode(), headers)


def audit(edit: dict[str, object], *, fresh: bool = False) -> dict[str, object]:
    request = audit_request(edit, fresh=fresh)
    with urllib.request.urlopen(request, timeout=300) as response:
        result: dict[str, object] = json.load(response)
        return result


def points_at_change(
    flags: list[dict[str, object]], changed: list[dict[str, object]]
) -> bool:
    """True when a flag's words sit inside (or contain) a sentence the later editor changed."""
    targets = [plain(str(c.get("added_sentence") or c)) for c in changed]
    targets = [t for t in targets if t]
    for flag in flags:
        anchor = plain(str(flag.get("anchor_text", "")))
        if not anchor:
            continue
        if any(anchor in t or t in anchor for t in targets):
            return True
    return False


def _changed(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [v if isinstance(v, dict) else {"added_sentence": str(v)} for v in value]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    edits = [
        json.loads(line)
        for path in args.files
        for line in Path(path).read_text(encoding="utf-8").splitlines()
    ]

    def score(edit: dict[str, object]) -> dict[str, object]:
        started = time.monotonic()
        try:
            result = audit(edit)
            error = None
        except Exception as exc:  # noqa: BLE001 - record and continue
            result, error = {}, f"{type(exc).__name__}: {exc}"
        raw_flags = result.get("flags", [])
        flags = (
            [f for f in raw_flags if isinstance(f, dict)]
            if isinstance(raw_flags, list)
            else []
        )
        tiers = {str(f.get("tier")) for f in flags}
        row = {
            "lang": edit["lang"],
            "page_title": edit["page_title"],
            "rev_id": edit.get("rev_id"),
            "label": edit["label"],
            "error": error,
            "flagged": "admin" if "admin" in tiers else "review" if flags else "none",
            "kinds": sorted({str(f.get("kind")) for f in flags}),
            "points_at_change": points_at_change(
                flags, _changed(edit.get("changed_by_later"))
            ),
            "seconds": round(time.monotonic() - started, 1),
            "flags": [
                {k: f.get(k) for k in ("kind", "tier", "anchor_text", "reason")}
                for f in flags
            ],
        }
        print(
            row["lang"],
            row["label"],
            row["flagged"],
            row["kinds"],
            "points" if row["points_at_change"] else "",
            row["seconds"],
            "s",
            error or "",
            flush=True,
        )
        return row

    # The API bounds its own Gemini concurrency; 4 audits in flight keep it busy.
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(score, edits))
    (out / "rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    table: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = (str(row["lang"]), str(row["label"]))
        table[key]["n"] += 1
        table[key][str(row["flagged"])] += 1
        table[key]["points_at_change"] += bool(row["points_at_change"])
        table[key]["error"] += bool(row["error"])
    lines = [
        "| lang | ground truth | n | admin | review | none | flag points at the later change | errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (lang, label), c in sorted(table.items()):
        lines.append(
            f"| {lang} | {label} | {c['n']} | {c['admin']} | {c['review']} | {c['none']} | {c['points_at_change']} | {c['error']} |"
        )
    (out / "table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

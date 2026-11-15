"""Flask routes for the optional explicit audit tab.

GET routes only read cached material.  The detector is contacted only by the
scan button's POST request.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

try:
    import requests
except ModuleNotFoundError:  # stdlib fallback keeps fixture tests dependency-free
    from urllib.error import URLError
    from urllib.request import Request, urlopen
    class _Response:
        def __init__(self, response): self.response=response
        def raise_for_status(self):
            if not 200 <= self.response.status < 300: raise _Requests.RequestException('HTTP '+str(self.response.status))
        def json(self): return json.load(self.response)
    class _Requests:
        class RequestException(Exception): pass
        @staticmethod
        def post(url, json, timeout, headers=None):
            try:
                request_headers = {"Content-Type": "application/json", **(headers or {})}
                return _Response(urlopen(Request(url, data=__import__('json').dumps(json).encode(), headers=request_headers), timeout=timeout))
            except (OSError, URLError) as error: raise _Requests.RequestException(str(error)) from error
    requests=_Requests()
from flask import Blueprint, abort, jsonify, render_template, request

from flags_tab import RevisionRef, audit_payload, block_revisions, rank_revisions
from revision_text import cache_root, fetch_history, fetch_revision

bp = Blueprint("flags", __name__)
PAGE_CREATION_TEXT_LIMIT = 60_000


def fixture_enabled() -> bool:
    return os.environ.get("LANGGAP_FIXTURES") == "1"


def fixture_context(topic: str) -> dict[str, Any] | None:
    if not fixture_enabled() or topic != "Q-demo":
        return None
    path = Path(__file__).with_name("tests_fixtures") / "article_demo.json"
    return json.loads(path.read_text(encoding="utf-8"))


def article_context(topic: str, requested_lang: str | None = None) -> dict[str, Any]:
    """Build the non-skyline Flags context from the local article snapshot."""
    from core import LANGS, connect
    requested_lang = requested_lang if requested_lang is not None else request.args.get("lang", "")
    if requested_lang and requested_lang not in LANGS:
        abort(400, description="Choose an available article language.")
    with connect() as db, db.cursor() as cursor:
        cursor.execute("SELECT * FROM article WHERE wikidata_id=%s", (topic,))
        articles = {str(row["lang"]): row for row in cursor.fetchall()}
    if not articles:
        abort(404)
    lang = requested_lang or next((item for item in ("en", "fi", "sv") if item in articles), next(iter(articles)))
    if lang not in articles:
        abort(404, description="This language is absent from the local snapshot.")
    article = articles[lang]
    context: dict[str, Any] = {
        "topic": topic, "title": article["title"], "current_lang": lang,
        "articles": articles, "article": article, "standalone": True,
    }
    try:
        history = fetch_history(lang, int(article["page_id"]), int(article["rev_id"] or 0), str(article["title"]))
        context["block_revisions"] = [dict(row, lang=lang, url=str(article.get("url") or "")) for row in history]
    except (RuntimeError, TypeError, ValueError) as error:
        # A network failure must not turn into a plausible-but-empty history list.
        context["history_error"] = str(error)
        context["block_revisions"] = []
    return context


def tracker_or_fixture(topic: str, requested_lang: str | None = None) -> dict[str, Any]:
    fixture = fixture_context(topic)
    if fixture is not None:
        fixture["standalone"] = not any(key in request.args for key in ("run", "group", "stamp", "occurrence"))
        return fixture
    if not any(key in request.args for key in ("run", "group", "stamp", "occurrence")):
        return article_context(topic, requested_lang)
    from skyline import tracker_context
    args = request.args.copy(); args["topic"] = topic
    try:
        return tracker_context(topic, args)
    except ValueError as error:
        abort(400, description=str(error))
    except LookupError as error:
        abort(404, description=str(error))


def audit_path(ref: RevisionRef) -> Path:
    return cache_root() / "audits" / f"{ref.lang}-{ref.revision_id}.json"


def page_path(ref: RevisionRef) -> Path:
    return cache_root() / "pages" / f"{ref.lang}-{ref.revision_id}.json"


def cached_audit(ref: RevisionRef, context: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = context.get("audits", {}).get(str(ref.revision_id)) if isinstance(context.get("audits"), Mapping) else None
    if isinstance(fixture, dict):
        return dict(fixture)
    try:
        path = audit_path(ref)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data.setdefault("status", "ok")
        data.setdefault(
            "stored_at",
            datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )
        return data
    except (OSError, ValueError):
        return None


def revision_rows(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref in block_revisions(context):
        audit = cached_audit(ref, context)
        source = next((item for item in context.get("block_revisions", ()) if int(item.get("revision", item.get("rev_id", 0)) or 0) == ref.revision_id), {})
        rows.append({"lang": ref.lang, "revision": ref.revision_id, "title": ref.title, "timestamp": ref.timestamp,
                     "user": str(source.get("user", "")), "comment": str(source.get("comment", "")),
                     "status": audit.get("status", "cached") if audit else "not scanned", "flags": audit.get("flags", []) if audit else []})
    # A clean source history remains newest-first until an audit exists to rank.
    return rank_revisions(rows) if any(row["status"] != "not scanned" for row in rows) else rows


def diff_html(old: str, new: str) -> str:
    """Render a full-width, word-level diff using the native anchor classes."""
    old_tokens = re.findall(r"\s+|\w+|[^\w\s]", old)
    new_tokens = re.findall(r"\s+|\w+|[^\w\s]", new)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
    old_html: list[str] = []
    new_html: list[str] = []
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        old_text = html.escape("".join(old_tokens[a0:a1]))
        new_text = html.escape("".join(new_tokens[b0:b1]))
        if opcode == "equal":
            old_html.append(old_text)
            new_html.append(new_text)
        elif opcode == "delete":
            old_html.append(f'<del class="diffchange">{old_text}</del>')
        elif opcode == "insert":
            new_html.append(f'<ins class="diffchange">{new_text}</ins>')
        else:
            old_html.append(f'<del class="diffchange">{old_text}</del>')
            new_html.append(f'<ins class="diffchange">{new_text}</ins>')
    return (
        '<table class="flags-diff diff mw-diff-inline"><thead><tr>'
        '<th scope="col">Prior revision</th><th scope="col">Selected revision</th>'
        '</tr></thead><tbody><tr>'
        f'<td class="mw-diff-inline-deleted" data-diff-side="old">{"".join(old_html)}</td>'
        f'<td class="mw-diff-inline-added" data-diff-side="new">{"".join(new_html)}</td>'
        '</tr></tbody></table>'
    )


def response_payload(ref: RevisionRef, context: Mapping[str, Any], scan: bool, fresh: bool = False) -> dict[str, Any]:
    # The synthetic fixture remains offline even when exercising the fresh UI.
    audit = cached_audit(ref, context) if (not fresh or isinstance(context.get("audits"), Mapping)) else None
    if audit is not None:
        old = str(audit.get("old_wikitext", "")); new = str(audit.get("new_wikitext", ""))
        if not old and not new:
            return {"status": "unavailable", "error": "Cached audit has no revision text; no empty diff was rendered.", "flags": []}
        return dict(audit, stored=True, diff_html=diff_html(old, new))
    if not scan:
        return {"status": "unavailable", "flags": [], "error": "Not scanned yet. Select Scan to make an explicit detector request."}
    try:
        new_record = fetch_revision(ref.lang, ref.revision_id)
        parent_value = new_record.get("parent_id")
        parent = int(parent_value if parent_value is not None else ref.parent_id or 0)
        page_created = not parent
        truncated = page_created and len(str(new_record["wikitext"])) > PAGE_CREATION_TEXT_LIMIT
        new_wikitext = str(new_record["wikitext"])[:PAGE_CREATION_TEXT_LIMIT] if truncated else str(new_record["wikitext"])
        if page_created:
            old_wikitext = ""
        else:
            try:
                old_record = fetch_revision(ref.lang, parent)
            except (OSError, RuntimeError, ValueError, KeyError):
                return {"status": "unavailable", "flags": [], "error": "The previous revision is hidden or deleted, so this edit cannot be compared."}
            if "texthidden" in old_record or "missing" in old_record:
                return {"status": "unavailable", "flags": [], "error": "The previous revision is hidden or deleted, so this edit cannot be compared."}
            old_wikitext = str(old_record["wikitext"])
        scoped = RevisionRef(ref.lang, ref.revision_id, str(new_record.get("title") or ref.title), ref.timestamp, ref.url, parent)
        body = audit_payload(scoped, old_wikitext, new_wikitext)
        api_url = os.environ.get("PALIMPSEST_API_URL", "http://127.0.0.1:8765").rstrip("/") + "/api/v1/audit-diff"
        response = requests.post(api_url, json=body, timeout=90,
                                 headers={"X-Palimpsest-Fresh": "1"} if fresh else {})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("invalid detector response")
        result.update(
            status="ok",
            old_wikitext=body["old_wikitext"],
            new_wikitext=body["new_wikitext"],
            stored_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        if page_created:
            result.update(page_created=True, truncated=truncated)
        path = audit_path(ref); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return dict(result, diff_html=diff_html(body["old_wikitext"], body["new_wikitext"]))
    except (requests.RequestException, OSError, RuntimeError, ValueError, KeyError) as error:
        return {"status": "error", "flags": [], "error": f"Audit unavailable: {error}"}


def rendered_page_html(wikitext: str, lang: str, title: str) -> str:
    """Use the existing safe renderer, retaining a small plain-text fallback."""
    try:
        from article_render import render_article
        rendered, _contents = render_article(wikitext, lang, title)
        return str(rendered)
    except (ImportError, ValueError, TypeError):
        paragraphs = [html.escape(part) for part in wikitext.split("\n\n") if part.strip()]
        return "".join(f"<p>{part}</p>" for part in paragraphs) or "<p>No revision text is available.</p>"


def cached_page_audit(ref: RevisionRef, context: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = context.get("page_audits", {}).get(str(ref.revision_id)) if isinstance(context.get("page_audits"), Mapping) else None
    if isinstance(fixture, dict):
        return dict(fixture)
    try:
        path = page_path(ref)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data.setdefault(
            "stored_at",
            datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )
        return data
    except (OSError, ValueError):
        return None


def page_response_payload(ref: RevisionRef, context: Mapping[str, Any], scan: bool,
                          fresh: bool = False) -> dict[str, Any]:
    # Fixture re-checks are deterministic and must not contact a detector.
    result = cached_page_audit(ref, context) if (not fresh or isinstance(context.get("page_audits"), Mapping)) else None
    stored = result is not None
    if result is None and not scan:
        return {"status": "unavailable", "flags": [], "error": "Not checked yet. Select Check this page to make an explicit detector request."}
    try:
        if result is None:
            fixture_article = context.get("articles", {}).get(ref.lang) if isinstance(context.get("articles"), Mapping) else None
            if isinstance(fixture_article, Mapping) and fixture_enabled():
                wikitext = str(fixture_article.get("text", ""))
            else:
                wikitext = str(fetch_revision(ref.lang, ref.revision_id)["wikitext"])
            body = {"lang_code": ref.lang, "page_title": ref.title,
                    "revision_id": ref.revision_id, "wikitext": wikitext}
            api_url = os.environ.get("PALIMPSEST_API_URL", "http://127.0.0.1:8765").rstrip("/") + "/api/v1/audit-page"
            response = requests.post(api_url, json=body, timeout=110,
                                     headers={"X-Palimpsest-Fresh": "1"} if fresh else {})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("invalid detector response")
            result.update(wikitext=wikitext)
            if result.get("status", "ok") == "ok":
                result["stored_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
                path = page_path(ref); path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        output = dict(result)
        output.setdefault("status", "ok")
        output.setdefault("flags", [])
        if stored:
            output["stored"] = True
        wikitext = str(output.get("wikitext") or context.get("articles", {}).get(ref.lang, {}).get("text", ""))
        output["page_html"] = rendered_page_html(wikitext, ref.lang, ref.title)
        return output
    except (requests.RequestException, OSError, RuntimeError, ValueError, KeyError) as error:
        return {"status": "error", "flags": [], "error": f"Page consistency is unavailable: {error}"}


@bp.get("/article/<topic>")
def article(topic: str):
    if not (topic == "Q-demo" and fixture_enabled()) and not re.fullmatch(r"Q\d{1,15}", topic):
        abort(404)
    context = tracker_or_fixture(topic)
    tab = request.args.get("tab", "language")
    if tab not in ("language", "flags"):
        abort(400, description="Choose the Language or Flags tab.")
    refs = revision_rows(context)
    selected = request.args.get("revision", type=int) or (refs[0]["revision"] if refs else None)
    selected_ref = next((ref for ref in block_revisions(context) if ref.revision_id == selected), None)
    audit = response_payload(selected_ref, context, False) if selected_ref else None
    # The historical language panel is the same existing template body, not a duplicate reviewer.
    context.update(topic=topic, title=context.get("title", topic), tab=tab, revisions=refs,
                   selected_revision=selected, audit=audit, fixture=fixture_enabled())
    return render_template("article_tabs.html", **context)


@bp.get("/api/flags/revisions")
def revisions_api():
    topic = request.args.get("topic", "")
    lang = request.args.get("lang")
    context = tracker_or_fixture(topic, lang)
    rows = revision_rows(context)
    if lang:
        rows = [row for row in rows if row["lang"] == lang]
    return jsonify(revisions=rows)


@bp.post("/api/flags/audit")
def audit_api():
    data = request.get_json(silent=True) or {}
    topic, lang = str(data.get("topic", "")), str(data.get("lang", ""))
    try:
        revision = int(data.get("revision"))
    except (TypeError, ValueError):
        return jsonify(status="error", error="A numeric revision is required.", flags=[]), 400
    context = tracker_or_fixture(topic, lang)
    ref = next((item for item in block_revisions(context) if item.lang == lang and item.revision_id == revision), None)
    if ref is None:
        return jsonify(status="error", error="That revision is not in this block's current edition.", flags=[]), 404
    return jsonify(
        response_payload(
            ref,
            context,
            bool(data.get("scan")),
            request.args.get("fresh") == "1",
        )
    )


@bp.post("/api/flags/page")
def page_api():
    data = request.get_json(silent=True) or {}
    topic, lang = str(data.get("topic", "")), str(data.get("lang", ""))
    context = tracker_or_fixture(topic, lang)
    refs = block_revisions(context)
    try:
        revision = int(data.get("revision")) if data.get("revision") is not None else None
    except (TypeError, ValueError):
        return jsonify(status="error", error="A numeric revision is required.", flags=[]), 400
    ref = next((item for item in refs if item.lang == lang and (revision is None or item.revision_id == revision)), None)
    if ref is None:
        return jsonify(status="error", error="That revision is not available for this article.", flags=[]), 404
    return jsonify(
        page_response_payload(
            ref,
            context,
            bool(data.get("scan")),
            request.args.get("fresh") == "1",
        )
    )

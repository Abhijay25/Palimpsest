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
        def get(url, timeout):
            try: return _Response(urlopen(url, timeout=timeout))
            except (OSError, URLError) as error: raise _Requests.RequestException(str(error)) from error
        @staticmethod
        def post(url, json, timeout, headers=None):
            try:
                request_headers = {"Content-Type": "application/json", **(headers or {})}
                return _Response(urlopen(Request(url, data=__import__('json').dumps(json).encode(), headers=request_headers), timeout=timeout))
            except (OSError, URLError) as error: raise _Requests.RequestException(str(error)) from error
    requests=_Requests()
from flask import Blueprint, abort, jsonify, render_template, request, send_file, redirect

from flags_tab import RevisionRef, audit_payload, block_revisions, rank_revisions
from revision_text import cache_root, fetch_history, fetch_revision

bp = Blueprint("flags", __name__)
PAGE_CREATION_TEXT_LIMIT = 60_000


@bp.get("/assets/flags/stacking.js")
def shared_flag_stacking():
    # Both the native extension and preview use the same collision-aware layout.
    path = Path(__file__).resolve().parents[2] / "infra/wiki/extensions/PalimpsestFlags/resources/stacking.js"
    return send_file(path, mimetype="application/javascript")


def detector_failure(error: Exception) -> str:
    """Keep transport errors, internal addresses and provider details out of the UI."""
    if type(error).__name__=="PersistenceError":return str(error)
    if isinstance(error, requests.RequestException):
        response = getattr(error, "response", None)
        code = getattr(response, "status_code", None)
        if code in (401, 403):
            return "The detector could not authenticate. Check its provider credentials."
        if code == 429:
            return "The detector is rate limited. Wait before trying again."
        if code in (502, 503, 504):
            return "The detector is unavailable or its provider is not configured. Check the detector service and try again."
        if code == 422:
            return "The detector rejected this revision. Its request format or text size is unsupported."
        return "Cannot reach the detector. Start the detector service, then try again."
    if isinstance(error, DetectorResultError):
        return str(error)
    if isinstance(error, RuntimeError):
        return "The selected revision text is unavailable. Try another revision."
    return "The scan could not be completed. Please try again; no successful result was saved."


class DetectorResultError(ValueError):
    pass


def validate_detector_result(result):
    if not isinstance(result, dict) or not isinstance(result.get("flags"), list):
        raise DetectorResultError("The detector returned an invalid response. No result was saved.")
    if result.get("status", "ok") != "ok":
        if "timeout" in str(result.get("error", "")).lower():
            raise DetectorResultError("The detector timed out before finishing. Retry the check or choose another revision; no successful result was saved.")
        raise DetectorResultError("The detector could not complete the scan. Check its provider configuration and try again; no successful result was saved.")
    return result


def validate_page_result(result):
    """Accept a completed page audit or its explicit partial result."""
    if not isinstance(result, dict) or not isinstance(result.get("flags"), list):
        raise DetectorResultError("The detector returned an invalid response. No result was saved.")
    if result.get("status", "ok") not in {"ok", "partial"}:
        return validate_detector_result(result)
    return result


@bp.get("/api/flags/health")
def detector_health():
    if fixture_enabled():
        return jsonify(available=True, configured=True, message="Offline fixture; scans stay local.")
    base = os.environ.get("PALIMPSEST_API_URL", "http://127.0.0.1:8765").rstrip("/")
    try:
        response = requests.get(base + "/healthz", timeout=3)
        response.raise_for_status()
        data = response.json()
        configured = isinstance(data, dict) and data.get("judge_configured") is True
        return jsonify(available=True, configured=configured, message=(
            "Detector ready. Scans run only when requested." if configured else
            "Detector is running, but Gemini is not configured. Configure its credentials and enable Gemini to scan."
        ))
    except (requests.RequestException, OSError, ValueError):
        return jsonify(available=False, configured=False,
                       message="Detector is offline. Start the preview with its detector service, then retry.")


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
    if isinstance(fixture, dict) and fixture.get("status", "ok") == "ok":
        return dict(fixture)
    try:
        path = audit_path(ref)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("status", "ok") != "ok":
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


def _word_diff(old: str, new: str) -> tuple[str, str]:
    """Return escaped, word-level markup for a single pair of source lines."""
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
    return "".join(old_html), "".join(new_html)


def _diff_hunks(old_lines: list[str], new_lines: list[str], context: int = 2) -> list[tuple[int, int]]:
    """Group changed opcodes when their two-line contexts touch."""
    opcodes = difflib.SequenceMatcher(a=old_lines, b=new_lines).get_opcodes()
    changes = [index for index, opcode in enumerate(opcodes) if opcode[0] != "equal"]
    if not changes:
        return []
    hunks: list[tuple[int, int]] = []
    first = last = changes[0]
    for index in changes[1:]:
        _tag, previous_a0, previous_a1, previous_b0, previous_b1 = opcodes[last]
        _tag, a0, _a1, b0, _b1 = opcodes[index]
        if a0 - previous_a1 <= context * 2 or b0 - previous_b1 <= context * 2:
            last = index
        else:
            hunks.append((first, last))
            first = last = index
    hunks.append((first, last))
    return hunks


def diff_html(old: str, new: str) -> str:
    """Render bounded, line-numbered changed hunks with native anchor cells."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    opcodes = difflib.SequenceMatcher(a=old_lines, b=new_lines).get_opcodes()
    # A page creation has no unchanged material to collapse. Its caller already
    # bounds the first revision before it reaches this renderer.
    page_creation = not old_lines or not new_lines
    hunks = [(0, len(opcodes) - 1)] if page_creation and opcodes else _diff_hunks(old_lines, new_lines)
    rows: list[str] = []
    previous_a = previous_b = 0
    for first, last in hunks:
        first_opcode, last_opcode = opcodes[first], opcodes[last]
        _tag, first_a0, _first_a1, first_b0, _first_b1 = first_opcode
        _tag, _last_a0, last_a1, _last_b0, last_b1 = last_opcode
        start_a = max(0, first_a0 - (0 if page_creation else 2))
        start_b = max(0, first_b0 - (0 if page_creation else 2))
        end_a = min(len(old_lines), last_a1 + (0 if page_creation else 2))
        end_b = min(len(new_lines), last_b1 + (0 if page_creation else 2))
        skipped = max(start_a - previous_a, start_b - previous_b)
        if rows and skipped:
            rows.append(f'<tr class="flags-diff-gap"><td colspan="2">… {skipped} unchanged line{"s" if skipped != 1 else ""} collapsed …</td></tr>')
        rows.append(
            '<tr class="flags-diff-hunk-heading">'
            f'<th scope="col">Line {start_a + 1}:</th><th scope="col">Line {start_b + 1}:</th>'
            '</tr>'
        )
        cursor_a, cursor_b = start_a, start_b
        if first and opcodes[first - 1][0] == "equal":
            _tag, a0, a1, b0, b1 = opcodes[first - 1]
            context_a, context_b = max(a0, start_a), max(b0, start_b)
            count = min(a1 - context_a, b1 - context_b)
            for offset in range(max(0, count)):
                old_index, new_index = context_a + offset, context_b + offset
                text = html.escape(old_lines[old_index])
                rows.append(
                    '<tr><td class="mw-diff-inline-deleted" data-diff-side="old">'
                    f'<span class="flags-diff-line-number">{old_index + 1}</span>{text}</td>'
                    '<td class="mw-diff-inline-added" data-diff-side="new">'
                    f'<span class="flags-diff-line-number">{new_index + 1}</span>{text}</td></tr>'
                )
            cursor_a, cursor_b = context_a + count, context_b + count
        for index in range(first, last + 1):
            tag, a0, a1, b0, b1 = opcodes[index]
            # Equal ranges at a hunk boundary provide its two lines of context.
            left, right = max(a0, cursor_a), min(a1, end_a)
            new_left, new_right = max(b0, cursor_b), min(b1, end_b)
            if tag == "equal":
                count = min(right - left, new_right - new_left)
                for offset in range(count):
                    text = html.escape(old_lines[left + offset])
                    rows.append(
                        '<tr><td class="mw-diff-inline-deleted" data-diff-side="old">'
                        f'<span class="flags-diff-line-number">{left + offset + 1}</span>{text}</td>'
                        '<td class="mw-diff-inline-added" data-diff-side="new">'
                        f'<span class="flags-diff-line-number">{new_left + offset + 1}</span>{text}</td></tr>'
                    )
                cursor_a, cursor_b = max(cursor_a, right), max(cursor_b, new_right)
                continue
            old_chunk = old_lines[max(a0, cursor_a):min(a1, end_a)]
            new_chunk = new_lines[max(b0, cursor_b):min(b1, end_b)]
            for offset in range(max(len(old_chunk), len(new_chunk))):
                old_text = old_chunk[offset] if offset < len(old_chunk) else ""
                new_text = new_chunk[offset] if offset < len(new_chunk) else ""
                old_markup, new_markup = _word_diff(old_text, new_text)
                if tag == "delete" or (tag == "replace" and not new_text):
                    old_markup = f'<del class="diffchange">{html.escape(old_text)}</del>'
                if tag == "insert" or (tag == "replace" and not old_text):
                    new_markup = f'<ins class="diffchange">{html.escape(new_text)}</ins>'
                old_number = a0 + offset + 1 if offset < len(old_chunk) else ""
                new_number = b0 + offset + 1 if offset < len(new_chunk) else ""
                rows.append(
                    '<tr><td class="mw-diff-inline-deleted" data-diff-side="old">'
                    f'<span class="flags-diff-line-number">{old_number}</span>{old_markup}</td>'
                    '<td class="mw-diff-inline-added" data-diff-side="new">'
                    f'<span class="flags-diff-line-number">{new_number}</span>{new_markup}</td></tr>'
                )
            cursor_a, cursor_b = max(cursor_a, min(a1, end_a)), max(cursor_b, min(b1, end_b))
        # Trailing equal context follows the last changed opcode in each hunk.
        if last + 1 < len(opcodes) and opcodes[last + 1][0] == "equal":
            _tag, a0, a1, b0, b1 = opcodes[last + 1]
            count = min(end_a - max(a0, cursor_a), end_b - max(b0, cursor_b), a1 - a0, b1 - b0)
            for offset in range(max(0, count)):
                old_index, new_index = max(a0, cursor_a) + offset, max(b0, cursor_b) + offset
                text = html.escape(old_lines[old_index])
                rows.append(
                    '<tr><td class="mw-diff-inline-deleted" data-diff-side="old">'
                    f'<span class="flags-diff-line-number">{old_index + 1}</span>{text}</td>'
                    '<td class="mw-diff-inline-added" data-diff-side="new">'
                    f'<span class="flags-diff-line-number">{new_index + 1}</span>{text}</td></tr>'
                )
        previous_a, previous_b = end_a, end_b
    if not rows:
        rows.append('<tr class="flags-diff-gap"><td colspan="2">No text changes.</td></tr>')
    return (
        '<table class="flags-diff diff mw-diff-inline"><thead><tr>'
        '<th scope="col">Prior revision</th><th scope="col">Selected revision</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )


def pending_result(ref, context, mode):
    if not context.get('topic') or fixture_enabled():return None
    path=cache_root()/'pending-issues'/f'{mode}-{ref.lang}-{ref.revision_id}.json'
    if not path.exists():return None
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('topic')!=context['topic']:raise RuntimeError('The pending assessment does not match this article.')
    return validate_detector_result(data['result'])


def save_issue_scan(ref,result,context,mode,cached=False):
    if not context.get('topic') or fixture_enabled():return result
    import issues
    from dataclasses import replace
    from revision_text import cached_revision
    record=cached_revision(ref.lang,ref.revision_id) or {}
    ref=replace(ref,parent_id=ref.parent_id or record.get('parent_id'),timestamp=ref.timestamp or record.get('timestamp',''))
    result=dict(result)
    if cached and not result.get('_issue_assessment'):
        result['_issue_assessment']=issues.identity('cache',context['topic'],ref.lang,ref.revision_id,mode,result)
        cache=page_path(ref) if mode=='page' else audit_path(ref)
        if cache.exists():result.setdefault('_issue_assessed_at',__import__('datetime').datetime.fromtimestamp(cache.stat().st_mtime,__import__('datetime').timezone.utc).isoformat())
    result.setdefault('_issue_assessment',issues.identity('scan',__import__('uuid').uuid4().hex))
    result.setdefault('_issue_assessed_at',issues.now())
    path=cache_root()/'pending-issues'/f'{mode}-{ref.lang}-{ref.revision_id}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(topic=context['topic'],result=result),ensure_ascii=False),encoding='utf-8')
    output=issues.store_scan(context['topic'],ref,result,mode)
    path.unlink(missing_ok=True)
    return output


def coverage_scan(ref,context,mode,state,note=''):
    if context.get('topic') and not fixture_enabled():
        from issues import scan_coverage
        scan_coverage(context['topic'],ref,mode,state,note)


def scan_failed(ref,context,mode,error):
    try:coverage_scan(ref,context,mode,'failed',detector_failure(error))
    except RuntimeError:pass


def response_payload(ref: RevisionRef, context: Mapping[str, Any], scan: bool, fresh: bool = False) -> dict[str, Any]:
    # The synthetic fixture remains offline even when exercising the fresh UI.
    recovered=pending_result(ref,context,'revision') if scan else None
    audit = recovered or (cached_audit(ref, context) if (not fresh or isinstance(context.get("audits"), Mapping)) else None)
    if audit is not None:
        old = str(audit.get("old_wikitext", "")); new = str(audit.get("new_wikitext", ""))
        if not old and not new:
            return {"status": "unavailable", "error": "Cached audit has no revision text; no empty diff was rendered.", "flags": []}
        if scan:
            try:audit=save_issue_scan(ref,audit,context,'revision',cached=True)
            except (RuntimeError,OSError) as error:return {'status':'error','flags':[],'error':detector_failure(error)}
        return dict(audit, stored=True, diff_html=diff_html(old, new))
    if not scan:
        return {"status": "unavailable", "flags": [], "error": "Not scanned yet. Select Scan to make an explicit detector request."}
    try:
        coverage_scan(ref,context,'revision','running')
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
        result = validate_detector_result(response.json())
        result.update(
            status="ok",
            old_wikitext=body["old_wikitext"],
            new_wikitext=body["new_wikitext"],
            stored_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        if page_created:
            result.update(page_created=True, truncated=truncated)
        result = save_issue_scan(scoped,result,context,'revision')
        path = audit_path(ref); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return dict(result, diff_html=diff_html(body["old_wikitext"], body["new_wikitext"]))
    except (requests.RequestException, OSError, RuntimeError, ValueError, KeyError) as error:
        scan_failed(ref,context,'revision',error)
        return {"status": "error", "flags": [], "error": detector_failure(error)}


def rendered_page_html(wikitext: str, lang: str, title: str) -> str:
    """Use the existing safe renderer, retaining a small plain-text fallback."""
    try:
        from article_render import render_article
        rendered, _contents = render_article(wikitext, lang, title)
        return str(rendered)
    except (ImportError, ValueError, TypeError):
        rendered: list[str] = []
        paragraph: list[str] = []
        def flush_paragraph() -> None:
            if paragraph:
                rendered.append(f"<p>{html.escape(chr(10).join(paragraph))}</p>")
                paragraph.clear()
        for line in wikitext.splitlines():
            heading = re.fullmatch(r"\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*", line)
            if heading:
                flush_paragraph()
                level, text = len(heading.group(1)), html.escape(heading.group(2))
                rendered.append(f"<h{level}>{text}</h{level}>")
            elif line.strip():
                paragraph.append(line)
            else:
                flush_paragraph()
        flush_paragraph()
        return "".join(rendered) or "<p>No revision text is available.</p>"


def cached_page_audit(ref: RevisionRef, context: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = context.get("page_audits", {}).get(str(ref.revision_id)) if isinstance(context.get("page_audits"), Mapping) else None
    if isinstance(fixture, dict) and fixture.get("status", "ok") == "ok":
        return dict(fixture)
    try:
        path = page_path(ref)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("status", "ok") != "ok":
            return None
        data.setdefault(
            "stored_at",
            datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )
        return data
    except (OSError, ValueError):
        return None


def page_response_payload(ref: RevisionRef, context: Mapping[str, Any], scan: bool,
                          fresh: bool = False, *, render_page: bool = True) -> dict[str, Any]:
    # Fixture re-checks are deterministic and must not contact a detector.
    recovered=pending_result(ref,context,'page') if scan else None
    result = recovered or (cached_page_audit(ref, context) if (not fresh or isinstance(context.get("page_audits"), Mapping)) else None)
    stored = result is not None
    if result is None and not scan:
        return {"status": "unavailable", "flags": [], "error": "Not checked yet. Select Check this page to make an explicit detector request."}
    try:
        if result is None:
            coverage_scan(ref,context,'page','running')
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
            result = validate_page_result(response.json())
            result.update(wikitext=wikitext)
            if result.get("status", "ok") == "partial":
                result["partial"] = True
            else:
                result["stored_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
                result = save_issue_scan(ref,result,context,'page')
                path = page_path(ref); path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        if scan and result.get("status", "ok") == "ok" and (
            recovered or not result.get('_issue_assessment')
        ):
            result = save_issue_scan(ref,result,context,'page',cached=True)
        output = dict(result)
        output.setdefault("status", "ok")
        output.setdefault("flags", [])
        if stored:
            output["stored"] = True
        if render_page:
            wikitext = str(output.get("wikitext") or context.get("articles", {}).get(ref.lang, {}).get("text", ""))
            output["page_html"] = rendered_page_html(wikitext, ref.lang, ref.title)
        else:
            # Native MediaWiki supplies the exact local ParserOutput itself.
            # Do not wait on a redundant source/preview renderer for saved reads.
            output.pop("page_html", None)
        return output
    except (requests.RequestException, OSError, RuntimeError, ValueError, KeyError) as error:
        scan_failed(ref,context,'page',error)
        return {"status": "error", "flags": [], "error": detector_failure(error)}


@bp.get("/article/<topic>")
def article(topic: str):
    if not (topic == "Q-demo" and fixture_enabled()) and not re.fullmatch(r"Q\d{1,15}", topic):
        abort(404)
    tab = request.args.get("tab", "article")
    if tab not in ("article", "language", "flags", "issues"):
        abort(400, description="Choose Article, Language differences or Flags.")
    historical = any(key in request.args for key in ("run", "group", "stamp", "occurrence"))
    fixture = fixture_context(topic)
    if tab in ('language','flags','issues') and fixture is None and not request.args.get('tools'):
        from issues_routes import legacy
        if historical and tab=='language':return legacy(topic)
        from urllib.parse import urlencode
        args=request.args.copy();args.poplist('tab');args.poplist('scan')
        if tab!='issues':args['origin']='language' if tab=='language' else 'flags'
        return redirect('/article/'+topic+'/issues?'+urlencode(list(args.items(multi=True))))
    if tab == "article" and not historical:
        from app import article_page
        return article_page(topic)
    if tab == "language" and fixture is None:
        from app import topic_page
        return topic_page(topic)
    context = tracker_or_fixture(topic)
    if tab == "article":
        return render_template("historical_article.html", **context)
    refs = revision_rows(context)
    selected = request.args.get("revision", type=int) or (refs[0]["revision"] if refs else None)
    selected_ref = next((ref for ref in block_revisions(context) if ref.revision_id == selected), None)
    audit = response_payload(selected_ref, context, False) if selected_ref else None
    # The historical language panel is the same existing template body, not a duplicate reviewer.
    context.update(topic=topic, title=context.get("title", topic), tab=tab, revisions=refs,
                   selected_revision=selected, audit=audit, fixture=fixture_context(topic) is not None,
                   article_text_html={
                       lang: rendered_page_html(str(article.get("text", "")), str(lang), str(article.get("title", context.get("title", topic))))
                       for lang, article in context.get("articles", {}).items()
                   })
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

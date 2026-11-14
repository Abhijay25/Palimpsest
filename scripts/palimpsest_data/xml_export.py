from __future__ import annotations

import html
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Iterator

from .io import DataError, atomic_write, iter_jsonl

NS = "http://www.mediawiki.org/xml/export-0.11/"
ET.register_namespace("", NS)


def _tag(parent: ET.Element, name: str, text: str | None = None, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, f"{{{NS}}}{name}", attrs)
    if text is not None:
        node.text = text
    return node


def _sha1_base36(hex_digest: str | None) -> str | None:
    if not hex_digest:
        return None
    if len(hex_digest) != 40:
        raise DataError("source SHA-1 must be a 40-character hexadecimal digest")
    try:
        value = int(hex_digest, 16)
    except ValueError as e:
        raise DataError("source SHA-1 must be a 40-character hexadecimal digest") from e
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = "0" if value == 0 else ""
    while value:
        value, remainder = divmod(value, 36)
        out = alphabet[remainder] + out
    return out


def mediawiki_xml(article: dict[str, Any], revisions: Iterable[dict[str, Any]]) -> bytes:
    records = sorted(revisions, key=lambda r: (r["timestamp"], r["source_revision_id"]))
    if not records:
        raise DataError("cannot export a page with no acquired revisions")
    ids = [r["source_revision_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise DataError(f"duplicate revision IDs in export for {article['source_wiki']}:{article['source_page_id']}")
    root = ET.Element(f"{{{NS}}}mediawiki", {"version": "0.11", "xml:lang": article["language"]})
    site = _tag(root, "siteinfo")
    _tag(site, "sitename", f"Wikipedia ({article['language']})")
    _tag(site, "dbname", article["source_wiki"])
    _tag(site, "base", f"https://{article['language']}.wikipedia.org/wiki/{article['title'].replace(' ', '_')}")
    _tag(site, "generator", "Palimpsest source-history exporter")
    namespaces = _tag(site, "namespaces")
    _tag(namespaces, "namespace", "", key="0")
    _tag(namespaces, "namespace", "Template", key="10")
    _tag(namespaces, "namespace", "Module", key="828")
    page = _tag(root, "page")
    _tag(page, "title", article["title"])
    _tag(page, "ns", str(article.get("namespace_id", 0)))
    _tag(page, "id", str(article["source_page_id"]))
    for rec in records:
        rev = _tag(page, "revision")
        _tag(rev, "id", str(rec["source_revision_id"]))
        if rec.get("source_parent_id") is not None:
            _tag(rev, "parentid", str(rec["source_parent_id"]))
        _tag(rev, "timestamp", rec["timestamp"])
        author = rec.get("author") or {}
        if author.get("hidden"):
            _tag(rev, "contributor", None, deleted="deleted")
        else:
            contributor = _tag(rev, "contributor")
            if author.get("kind") == "anonymous" and author.get("value"):
                _tag(contributor, "ip", str(author["value"]))
            elif author.get("value"):
                _tag(contributor, "username", str(author["value"]))
            else:
                _tag(contributor, "username", "Unknown")
        if rec.get("comment_hidden"):
            _tag(rev, "comment", None, deleted="deleted")
        elif rec.get("comment") is not None:
            _tag(rev, "comment", str(rec["comment"]))
        if rec.get("minor"):
            _tag(rev, "minor")
        model = rec.get("content_model") or "wikitext"
        content_format = rec.get("content_format") or "text/x-wiki"
        sha1_base36 = _sha1_base36(rec.get("source_sha1"))
        if sha1_base36:
            _tag(rev, "sha1", sha1_base36)
        _tag(rev, "model", model)
        _tag(rev, "format", content_format)
        text_attrs = {}
        if sha1_base36:
            text_attrs["sha1"] = sha1_base36
        if rec.get("content_hidden"):
            _tag(rev, "text", None, deleted="deleted")
        else:
            if rec.get("content") is None:
                raise DataError(f"revision {rec['source_revision_id']} has unavailable, non-hidden content and cannot be exported")
            content = rec["content"]
            text_attrs["bytes"] = str(len(content.encode("utf-8")))
            _tag(rev, "text", content, **text_attrs)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    try:
        ET.fromstring(xml)
    except ET.ParseError as e:
        raise DataError(f"generated MediaWiki XML is invalid: {e}") from e
    return xml


def export_article(path: Path, article: dict[str, Any], revisions: Iterable[dict[str, Any]]) -> str:
    data = mediawiki_xml(article, revisions)
    atomic_write(path, data)
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _escape_xml(value: str) -> str:
    for char in value:
        code = ord(char)
        if code not in (9, 10, 13) and not (0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF):
            raise DataError(f"source text contains XML 1.0 forbidden code point U+{code:04X}")
    return html.escape(value, quote=False)


def _stream_revision(out, rec: dict[str, Any]) -> None:
    out.write(b"    <revision>\n")
    out.write(f"      <id>{int(rec['source_revision_id'])}</id>\n".encode())
    if rec.get("source_parent_id") is not None:
        out.write(f"      <parentid>{int(rec['source_parent_id'])}</parentid>\n".encode())
    out.write(f"      <timestamp>{_escape_xml(rec['timestamp'])}</timestamp>\n".encode())
    author = rec.get("author") or {}
    if author.get("hidden"):
        out.write(b'      <contributor deleted="deleted" />\n')
    elif author.get("kind") == "anonymous" and author.get("value"):
        out.write(f"      <contributor><ip>{_escape_xml(str(author['value']))}</ip></contributor>\n".encode())
    else:
        username = str(author.get("value") or "Unknown")
        out.write(f"      <contributor><username>{_escape_xml(username)}</username></contributor>\n".encode())
    if rec.get("comment_hidden"):
        out.write(b'      <comment deleted="deleted" />\n')
    elif rec.get("comment") is not None:
        out.write(f"      <comment>{_escape_xml(str(rec['comment']))}</comment>\n".encode())
    if rec.get("minor"):
        out.write(b"      <minor />\n")
    model = _escape_xml(str(rec.get("content_model") or "wikitext"))
    content_format = _escape_xml(str(rec.get("content_format") or "text/x-wiki"))
    sha1_base36 = _sha1_base36(rec.get("source_sha1"))
    if sha1_base36:
        out.write(f"      <sha1>{sha1_base36}</sha1>\n".encode())
    out.write(f"      <model>{model}</model>\n      <format>{content_format}</format>\n".encode())
    if rec.get("content_hidden"):
        out.write(b'      <text deleted="deleted" />\n')
    else:
        content = rec.get("content")
        if content is None:
            raise DataError(f"revision {rec['source_revision_id']} has unavailable, non-hidden content and cannot be exported")
        attrs = f' bytes="{len(content.encode("utf-8"))}"'
        if sha1_base36:
            attrs += f' sha1="{sha1_base36}"'
        out.write(f"<text{attrs}>{_escape_xml(content)}</text>".encode())
        out.write(b"\n")
    out.write(b"    </revision>\n")


def export_article_stream(path: Path, article: dict[str, Any], batch_paths: list[Path], *, only_revision_ids: set[int] | None = None) -> str:
    """Write chronological XML using at most one 50-revision response batch in memory."""
    from .io import sha256_file
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            def write(data: bytes) -> None:
                out.write(data)
            title = _escape_xml(article["title"])
            base = f"https://{article['language']}.wikipedia.org/wiki/{article['title'].replace(' ', '_')}"
            write(b'<?xml version="1.0" encoding="utf-8"?>\n')
            write(f'<mediawiki xmlns="{NS}" version="0.11" xml:lang="{article["language"]}">\n'.encode())
            write(f"  <siteinfo><sitename>Wikipedia ({article['language']})</sitename><dbname>{article['source_wiki']}</dbname><base>{_escape_xml(base)}</base><generator>Palimpsest source-history exporter</generator><namespaces><namespace key=\"0\"></namespace><namespace key=\"10\">Template</namespace><namespace key=\"828\">Module</namespace></namespaces></siteinfo>\n".encode())
            write(f"  <page><title>{title}</title><ns>{article.get('namespace_id', 0)}</ns><id>{article['source_page_id']}</id>\n".encode())
            total = 0
            seen: set[int] = set()
            for batch_path in reversed(batch_paths):
                rows = list(iter_jsonl([batch_path]))
                for rec in reversed(rows):
                    rev = rec["source_revision_id"]
                    if only_revision_ids is not None and rev not in only_revision_ids:
                        continue
                    if rev in seen:
                        raise DataError(f"duplicate revision ID {rev} in XML export")
                    seen.add(rev)
                    _stream_revision(out, rec)
                    total += 1
            if total == 0:
                raise DataError("cannot export a page with no acquired revisions")
            write(b"  </page>\n</mediawiki>\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return sha256_file(path)

"""Live-page Wikipedia audit: deterministic date checks plus cited paragraph review."""

import argparse
import asyncio
import html
import re
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Literal, cast
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, Field

from palimpsest.crosslingual import (
    MEDIAWIKI_USER_AGENT,
    audit_single_language_claim,
    fetch_wikitext,
)
from palimpsest.judge import AsyncJudge
from palimpsest.pipeline import CACHE_DIR, STAGE1_CONCURRENCY
from palimpsest.reasons import REASON_TEXT, ReasonCode, reason_code
from palimpsest.schema import FlaggedSpan, Verdict
from palimpsest.sources import SourceFetcher
from palimpsest.stage0 import extract_ref_urls, strip_wikitext
from palimpsest.stealth.models import HiddenFinding, StealthStatus
from palimpsest.stealth.scanner import reportable_findings, scan

REQUEST_TIMEOUT_S: Final = 20.0
_MONTH_MESSAGE_NAMES: Final = (
    *[
        f"{month}"
        for month in (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    ],
    *[
        f"{month}-gen"
        for month in (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    ],
    *[
        month
        for month in (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        )
    ],
)
_MONTH_INDEX: Final = {
    f"{name}{suffix}": index + 1
    for suffix in ("", "-gen")
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )
}
_MONTH_INDEX.update(
    {
        name: index + 1
        for index, name in enumerate(
            (
                "jan",
                "feb",
                "mar",
                "apr",
                "may",
                "jun",
                "jul",
                "aug",
                "sep",
                "oct",
                "nov",
                "dec",
            )
        )
    }
)
_ISO_DATE_RE: Final = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_NUMERIC_DATE_RE: Final = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_REF_RE: Final = re.compile(r"<ref\b", re.IGNORECASE)


class FutureDateFinding(BaseModel):
    code: Literal["FUTURE_DATE"] = "FUTURE_DATE"
    rendered_date: str
    parsed_date: date
    revision_timestamp: datetime
    snippet: str
    location: Literal["reference", "body"]


class RevisionDateMismatchFinding(BaseModel):
    code: Literal["REVISION_DATE_MISMATCH"] = "REVISION_DATE_MISMATCH"
    url: str
    revid: int
    rendered_date: str
    parsed_date: date
    revision_timestamp: datetime
    snippet: str


class ParagraphAudit(BaseModel):
    index: int
    verdict: Verdict | None = None
    confidence: float | None = None
    reason: ReasonCode | None = None
    reason_text: str | None = None
    flagged_spans: list[FlaggedSpan] = Field(default_factory=list)
    neutral_rewrite: str | None = None
    ref_urls: list[str]
    latency_ms: float
    error: str | None = None


class PageAuditReport(BaseModel):
    lang: str
    title: str
    revision_id: int
    revision_timestamp: datetime
    stealth_status: StealthStatus
    stealth_findings: list[HiddenFinding]
    future_dates: list[FutureDateFinding]
    revision_date_mismatches: list[RevisionDateMismatchFinding]
    paragraphs_total: int
    paragraphs_with_refs: int
    paragraphs_audited: int
    partial: bool
    paragraph_audits: list[ParagraphAudit]
    judge_usage: dict[str, int] | None = None


class _Revision(BaseModel):
    revid: int
    timestamp: datetime


class _RevisionPage(BaseModel):
    revisions: list[_Revision] = Field(default_factory=list)


class _RevisionResponse(BaseModel):
    query: "_RevisionQuery | None" = None


class _RevisionQuery(BaseModel):
    pages: list[_RevisionPage] = Field(default_factory=list)


class _Message(BaseModel):
    name: str
    content: str | None = None


class _MessagesQuery(BaseModel):
    allmessages: list[_Message] = Field(default_factory=list)


class _MessagesResponse(BaseModel):
    query: _MessagesQuery | None = None


class _ParseResponse(BaseModel):
    parse: "_ParseResult"


class _ParseResult(BaseModel):
    text: str


class _TextPart(BaseModel):
    start: int
    end: int
    citation_id: int | None


class _RevisionLink(BaseModel):
    url: str
    start: int
    end: int
    citation_id: int | None


class _RenderedPage(BaseModel):
    text: str
    parts: list[_TextPart]
    revision_links: list[_RevisionLink]


class _RenderedHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self.parts: list[_TextPart] = []
        self.links: list[_RevisionLink] = []
        self._citation_stack: list[int] = []
        self._tag_citations: list[bool] = []
        self._next_citation = 0
        self._open_links: list[tuple[str, int, int | None]] = []

    def _citation(self, tag: str, attrs: dict[str, str | None]) -> bool:
        classes = attrs.get("class") or ""
        return tag == "cite" or (tag == "ol" and "references" in classes.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        is_citation = self._citation(tag, values)
        self._tag_citations.append(is_citation)
        if is_citation:
            self._next_citation += 1
            self._citation_stack.append(self._next_citation)
        if tag == "a" and values.get("href"):
            self._open_links.append(
                (cast(str, values["href"]), self._length(), self._citation_id())
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open_links:
            url, start, citation_id = self._open_links.pop()
            self.links.append(
                _RevisionLink(
                    url=url, start=start, end=self._length(), citation_id=citation_id
                )
            )
        if self._tag_citations:
            was_citation = self._tag_citations.pop()
            if was_citation and self._citation_stack:
                self._citation_stack.pop()

    def handle_data(self, data: str) -> None:
        if not data:
            return
        start = self._length()
        self.pieces.append(data)
        self.parts.append(
            _TextPart(
                start=start, end=start + len(data), citation_id=self._citation_id()
            )
        )
        self.pieces.append(" ")

    def _length(self) -> int:
        return sum(len(piece) for piece in self.pieces)

    def _citation_id(self) -> int | None:
        return self._citation_stack[-1] if self._citation_stack else None

    def result(self) -> _RenderedPage:
        return _RenderedPage(
            text="".join(self.pieces), parts=self.parts, revision_links=self.links
        )


def _api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


async def _api_get(
    client: httpx.AsyncClient, lang: str, params: dict[str, str]
) -> httpx.Response:
    try:
        response = await client.get(
            _api_url(lang),
            headers={"User-Agent": MEDIAWIKI_USER_AGENT},
            params=params,
            timeout=REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()
        return response
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"MediaWiki request for {lang}.wikipedia.org failed: {exc}"
        ) from exc


async def _latest_revision(
    client: httpx.AsyncClient, lang: str, title: str
) -> _Revision:
    response = await _api_get(
        client,
        lang,
        {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "redirects": "1",
            "rvprop": "ids|timestamp",
            "rvlimit": "1",
            "format": "json",
            "formatversion": "2",
        },
    )
    parsed = _RevisionResponse.model_validate_json(response.content)
    pages = parsed.query.pages if parsed.query is not None else []
    if not pages or not pages[0].revisions:
        raise RuntimeError(f"Wikipedia page not found: {lang}:{title}")
    return pages[0].revisions[0]


async def _rendered_html(
    client: httpx.AsyncClient, lang: str, title: str
) -> _RenderedPage:
    response = await _api_get(
        client,
        lang,
        {
            "action": "parse",
            "page": title,
            "prop": "text",
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
        },
    )
    parsed = _ParseResponse.model_validate_json(response.content)
    parser = _RenderedHTML()
    parser.feed(parsed.parse.text)
    return parser.result()


def _message_text(value: str) -> str:
    parser = _RenderedHTML()
    parser.feed(html.unescape(value))
    return " ".join(parser.result().text.split())


async def _month_names(client: httpx.AsyncClient, lang: str) -> dict[str, int]:
    response = await _api_get(
        client,
        lang,
        {
            "action": "query",
            "meta": "allmessages",
            "ammessages": "|".join(_MONTH_MESSAGE_NAMES),
            "amlang": lang,
            "format": "json",
            "formatversion": "2",
        },
    )
    parsed = _MessagesResponse.model_validate_json(response.content)
    messages = parsed.query.allmessages if parsed.query is not None else []
    names: dict[str, int] = {}
    for message in messages:
        month = _MONTH_INDEX.get(message.name)
        if message.content is None:
            continue
        text = _message_text(message.content).casefold()
        if month is not None and text:
            names[text] = month
    return names


_MONTH_CACHE: dict[str, dict[str, int]] = {}


async def month_names(client: httpx.AsyncClient, lang: str) -> dict[str, int]:
    """Get localized month spellings once per language for this process."""
    cached = _MONTH_CACHE.get(lang)
    if cached is None:
        cached = await _month_names(client, lang)
        _MONTH_CACHE[lang] = cached
    return cached


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parsed_dates(text: str, months: dict[str, int]) -> list[tuple[re.Match[str], date]]:
    """Find only numeric/ISO and locale-message-derived calendar dates."""
    results: list[tuple[re.Match[str], date]] = []
    occupied: list[tuple[int, int]] = []
    for pattern, groups in ((_ISO_DATE_RE, (1, 2, 3)), (_NUMERIC_DATE_RE, (3, 2, 1))):
        for match in pattern.finditer(text):
            value = _valid_date(*(int(match.group(index)) for index in groups))
            if value is not None:
                results.append((match, value))
                occupied.append(match.span())
    if not months:
        return sorted(results, key=lambda item: item[0].start())
    choices = "|".join(
        re.escape(name) for name in sorted(months, key=len, reverse=True)
    )
    token = rf"(?P<month>{choices})"
    patterns = (
        re.compile(
            rf"(?<!\w)(?P<day>\d{{1,2}})\.?\s+{token}\s+(?P<year>\d{{4}})(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<!\w){token}\s+(?P<day>\d{{1,2}}),?\s+(?P<year>\d{{4}})(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(rf"(?<!\w){token}\s+(?P<year>\d{{4}})(?!\w)", re.IGNORECASE),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            if any(
                match.start() < end and start < match.end() for start, end in occupied
            ):
                continue
            month = months.get(match.group("month").casefold())
            day = int(match.groupdict().get("day") or "1")
            value = _valid_date(int(match.group("year")), month or 0, day)
            if value is not None:
                results.append((match, value))
                occupied.append(match.span())
    return sorted(results, key=lambda item: item[0].start())


def _citation_id_at(page: _RenderedPage, offset: int) -> int | None:
    return next(
        (part.citation_id for part in page.parts if part.start <= offset < part.end),
        None,
    )


def _snippet(text: str, start: int, end: int) -> str:
    return " ".join(text[max(0, start - 100) : min(len(text), end + 100)].split())


def future_date_findings(
    page: _RenderedPage, revision: _Revision, months: dict[str, int]
) -> list[FutureDateFinding]:
    findings: list[FutureDateFinding] = []
    for match, value in parsed_dates(page.text, months):
        if value > revision.timestamp.date():
            in_citation = _citation_id_at(page, match.start()) is not None
            findings.append(
                FutureDateFinding(
                    rendered_date=match.group(0),
                    parsed_date=value,
                    revision_timestamp=revision.timestamp,
                    snippet=_snippet(page.text, match.start(), match.end()),
                    location="reference" if in_citation else "body",
                )
            )
    return findings


def _oldid(url: str) -> int | None:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.hostname.endswith(".wikipedia.org"):
        return None
    values = parse_qs(parsed.query).get("oldid")
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


async def _revision_timestamps(
    client: httpx.AsyncClient, links: list[_RevisionLink]
) -> dict[tuple[str, int], datetime]:
    grouped: defaultdict[str, list[int]] = defaultdict(list)
    for link in links:
        revid = _oldid(link.url)
        host = urlparse(link.url).hostname
        if revid is not None and host is not None and revid not in grouped[host]:
            grouped[host].append(revid)

    async def one(host: str, ids: list[int]) -> dict[tuple[str, int], datetime]:
        try:
            response = await client.get(
                f"https://{host}/w/api.php",
                headers={"User-Agent": MEDIAWIKI_USER_AGENT},
                params={
                    "action": "query",
                    "prop": "revisions",
                    "revids": "|".join(map(str, ids)),
                    "rvprop": "ids|timestamp",
                    "format": "json",
                    "formatversion": "2",
                },
                timeout=REQUEST_TIMEOUT_S,
            )
            response.raise_for_status()
            parsed = _RevisionResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValueError):
            return {}
        pages = parsed.query.pages if parsed.query is not None else []
        return {
            (host, item.revid): item.timestamp
            for page in pages
            for item in page.revisions
        }

    responses = await asyncio.gather(*(one(host, ids) for host, ids in grouped.items()))
    return {key: value for response in responses for key, value in response.items()}


async def revision_date_mismatches(
    client: httpx.AsyncClient, page: _RenderedPage, months: dict[str, int]
) -> list[RevisionDateMismatchFinding]:
    links = [link for link in page.revision_links if _oldid(link.url) is not None]
    timestamps = await _revision_timestamps(client, links)
    dates = parsed_dates(page.text, months)
    findings: list[RevisionDateMismatchFinding] = []
    for link in links:
        revid = _oldid(link.url)
        host = urlparse(link.url).hostname
        if (
            revid is None
            or host is None
            or (timestamp := timestamps.get((host, revid))) is None
        ):
            continue
        cited_dates = [
            item
            for item in dates
            if (
                _citation_id_at(page, item[0].start()) == link.citation_id
                if link.citation_id is not None
                else abs(item[0].start() - link.start) <= 200
            )
        ]
        for match, value in cited_dates:
            if abs((value - timestamp.date()).days) > 31:
                findings.append(
                    RevisionDateMismatchFinding(
                        url=link.url,
                        revid=revid,
                        rendered_date=match.group(0),
                        parsed_date=value,
                        revision_timestamp=timestamp,
                        snippet=_snippet(page.text, match.start(), match.end()),
                    )
                )
    return findings


def _paragraphs(wikitext: str) -> list[str]:
    return [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", wikitext)
        if paragraph.strip()
    ]


async def _audit_paragraphs(
    lang: str,
    title: str,
    paragraphs: list[str],
    judge: AsyncJudge,
    fetcher: SourceFetcher,
) -> list[ParagraphAudit]:
    semaphore = asyncio.Semaphore(STAGE1_CONCURRENCY)

    async def one(index: int, paragraph: str) -> ParagraphAudit:
        started = time.perf_counter()
        urls = extract_ref_urls(paragraph)
        try:
            async with semaphore:
                state = await audit_single_language_claim(
                    lang, title, paragraph, judge, fetcher
                )
            if state.verdict is None:
                return ParagraphAudit(
                    index=index,
                    ref_urls=urls,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=state.reason or "No verdict returned",
                )
            output_reason = reason_code_from_state(
                state.verdict, state.flagged_spans, paragraph
            )
            return ParagraphAudit(
                index=index,
                verdict=state.verdict,
                confidence=state.confidence,
                reason=output_reason,
                reason_text=REASON_TEXT.get(output_reason) if output_reason else None,
                flagged_spans=state.flagged_spans,
                neutral_rewrite=state.neutral_rewrite,
                ref_urls=urls,
                latency_ms=state.latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - one paragraph must not suppress the live report
            return ParagraphAudit(
                index=index,
                ref_urls=urls,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    return list(
        await asyncio.gather(
            *(one(index, paragraph) for index, paragraph in enumerate(paragraphs))
        )
    )


def reason_code_from_state(
    verdict: Verdict, flagged_spans: list[FlaggedSpan], paragraph: str
) -> ReasonCode | None:
    """Use the existing reason taxonomy when only a verdict is available."""
    from palimpsest.schema import AuditOutput, ExpandDirection

    return reason_code(
        AuditOutput(
            verdict=verdict,
            confidence=0.0,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=[],
            flagged_spans=flagged_spans,
            neutral_rewrite=None,
        ),
        "",
        strip_wikitext(paragraph),
    )


async def audit_page(
    lang: str,
    title: str,
    max_paragraphs: int = 12,
    judge: AsyncJudge | None = None,
    fetcher: SourceFetcher | None = None,
    client: httpx.AsyncClient | None = None,
) -> PageAuditReport:
    """Audit the current revision of one page; callers can inject all I/O for tests."""
    if max_paragraphs < 0:
        raise ValueError("max_paragraphs must be non-negative")
    owns_client = client is None
    mediawiki = client or httpx.AsyncClient(
        headers={"User-Agent": MEDIAWIKI_USER_AGENT}, timeout=REQUEST_TIMEOUT_S
    )
    try:
        revision_task = asyncio.create_task(_latest_revision(mediawiki, lang, title))
        wikitext_task = asyncio.create_task(fetch_wikitext(mediawiki, lang, title))
        html_task = asyncio.create_task(_rendered_html(mediawiki, lang, title))
        months_task = asyncio.create_task(month_names(mediawiki, lang))
        revision, wikitext, rendered, months = await asyncio.gather(
            revision_task, wikitext_task, html_task, months_task
        )
        if not wikitext:
            raise RuntimeError(
                f"Wikipedia page has no current wikitext: {lang}:{title}"
            )
        stealth = scan(wikitext, "WIKIPEDIA_DIFF")
        all_paragraphs = _paragraphs(wikitext)
        cited = [
            (index, paragraph)
            for index, paragraph in enumerate(all_paragraphs)
            if _REF_RE.search(paragraph)
        ]
        selected = cited[:max_paragraphs]
        paragraph_results: list[ParagraphAudit] = []
        if judge is not None and selected:
            used_fetcher = fetcher or SourceFetcher(None, CACHE_DIR)
            raw = await _audit_paragraphs(
                lang,
                title,
                [paragraph for _, paragraph in selected],
                judge,
                used_fetcher,
            )
            paragraph_results = [
                result.model_copy(update={"index": selected[position][0]})
                for position, result in enumerate(raw)
            ]
        usage = getattr(judge, "usage", None) if judge is not None else None
        return PageAuditReport(
            lang=lang,
            title=title,
            revision_id=revision.revid,
            revision_timestamp=revision.timestamp,
            stealth_status=stealth.stealth_status,
            stealth_findings=reportable_findings(stealth),
            future_dates=future_date_findings(rendered, revision, months),
            revision_date_mismatches=await revision_date_mismatches(
                mediawiki, rendered, months
            ),
            paragraphs_total=len(all_paragraphs),
            paragraphs_with_refs=len(cited),
            paragraphs_audited=len(paragraph_results),
            partial=judge is not None and len(cited) > len(selected),
            paragraph_audits=paragraph_results,
            judge_usage=usage
            if isinstance(usage, dict)
            and all(isinstance(k, str) and isinstance(v, int) for k, v in usage.items())
            else None,
        )
    finally:
        if owns_client:
            await mediawiki.aclose()


def _table(rows: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}}  {value}" for label, value in rows)


def render_page_report(report: PageAuditReport) -> str:
    rows = [
        ("page", f"{report.lang}:{report.title}"),
        ("revision", f"{report.revision_id} ({report.revision_timestamp.isoformat()})"),
        (
            "stealth",
            f"{report.stealth_status} ({len(report.stealth_findings)} findings)",
        ),
        ("future dates", str(len(report.future_dates))),
        ("revision date mismatches", str(len(report.revision_date_mismatches))),
        (
            "paragraphs",
            f"total={report.paragraphs_total} cited={report.paragraphs_with_refs} audited={report.paragraphs_audited}"
            + (" (partial)" if report.partial else ""),
        ),
        ("judge usage", str(report.judge_usage or "none")),
    ]
    return _table(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m palimpsest audit-page")
    parser.add_argument("--lang", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--max-paragraphs", type=int, default=12)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    judge: AsyncJudge | None = None
    if not args.no_judge:
        # The API module owns backend construction; defer its optional renderer stack
        # until this CLI needs a judge so deterministic library use stays lightweight.
        from palimpsest.api import get_judge_backend

        judge = get_judge_backend()
    try:
        report = asyncio.run(
            audit_page(args.lang, args.title, args.max_paragraphs, judge)
        )
    except (RuntimeError, ValueError) as exc:
        print(f"audit-page: {exc}")
        return 2
    print(render_page_report(report))
    if args.json is not None:
        args.json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return 0

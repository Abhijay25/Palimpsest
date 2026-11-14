"""Rendered-citation date checks shared by page and edit audits."""

import asyncio
import html
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Final, Literal, cast
from urllib.parse import parse_qs, quote, urlparse

import httpx
from pydantic import BaseModel, Field

from palimpsest.crosslingual import MEDIAWIKI_USER_AGENT

REQUEST_TIMEOUT_S: Final = 20.0
RATE_LIMIT_MAX_WAIT_S: Final = 2.0
_MONTH_MESSAGE_NAMES: Final = (
    *[
        month
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
_IGNORED_TAGS: Final = frozenset({"script", "style"})
_DATE_SCOPE_TAGS: Final = frozenset({"li", "cite", "p", "td", "dd"})


class FutureDateFinding(BaseModel):
    code: Literal["FUTURE_DATE"] = "FUTURE_DATE"
    url: str
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


CitationDateFinding = FutureDateFinding | RevisionDateMismatchFinding


class CitationDateScan(BaseModel):
    status: Literal["ok", "skipped", "unavailable"]
    findings: list[CitationDateFinding] = Field(default_factory=list)
    error: str | None = None


class _Message(BaseModel):
    name: str
    content: str | None = None


class _MessagesQuery(BaseModel):
    allmessages: list[_Message] = Field(default_factory=list)


class _MessagesResponse(BaseModel):
    query: _MessagesQuery | None = None


class _ParseResult(BaseModel):
    text: str


class _ParseResponse(BaseModel):
    parse: _ParseResult


class _Revision(BaseModel):
    revid: int
    timestamp: datetime


class _RevisionPage(BaseModel):
    revisions: list[_Revision] = Field(default_factory=list)


class _RevisionQuery(BaseModel):
    pages: list[_RevisionPage] = Field(default_factory=list)


class _RevisionResponse(BaseModel):
    query: _RevisionQuery | None = None


class _TextPart(BaseModel):
    start: int
    end: int
    citation_id: int | None
    element_id: int | None


class _DateScope(BaseModel):
    id: int
    start: int
    end: int | None = None


class _RevisionLink(BaseModel):
    url: str
    start: int
    end: int
    citation_id: int | None
    element_id: int | None


class RenderedPage(BaseModel):
    text: str
    parts: list[_TextPart]
    elements: list[_DateScope]
    revision_links: list[_RevisionLink]


class RenderedHTML(HTMLParser):
    """Collect visible rendered text while retaining reference/link locations."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self.parts: list[_TextPart] = []
        self.elements: list[_DateScope] = []
        self.links: list[_RevisionLink] = []
        self._citation_stack: list[int] = []
        self._tag_citations: list[bool] = []
        self._element_stack: list[_DateScope] = []
        self._tag_elements: list[_DateScope | None] = []
        self._ignored_tags: list[bool] = []
        self._next_citation = 0
        self._next_element = 0
        self._open_links: list[tuple[str, int, int | None, int | None]] = []

    def _citation(self, tag: str, attrs: dict[str, str | None]) -> bool:
        classes = attrs.get("class") or ""
        return tag == "cite" or (tag == "ol" and "references" in classes.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        ignored = bool(self._ignored_tags and self._ignored_tags[-1]) or (
            tag in _IGNORED_TAGS or "mw-editsection" in classes
        )
        self._ignored_tags.append(ignored)
        is_citation = not ignored and self._citation(tag, values)
        self._tag_citations.append(is_citation)
        element: _DateScope | None = None
        if not ignored and tag in _DATE_SCOPE_TAGS:
            self._next_element += 1
            element = _DateScope(id=self._next_element, start=self._length())
            self.elements.append(element)
            self._element_stack.append(element)
        self._tag_elements.append(element)
        if is_citation:
            self._next_citation += 1
            self._citation_stack.append(self._next_citation)
        if not ignored and tag == "a" and values.get("href"):
            self._open_links.append(
                (
                    cast(str, values["href"]),
                    self._length(),
                    self._citation_id(),
                    self._element_id(),
                )
            )

    def handle_endtag(self, tag: str) -> None:
        if not self._ignored_tags:
            return
        ignored = self._ignored_tags.pop()
        was_citation = self._tag_citations.pop()
        element = self._tag_elements.pop()
        if not ignored and tag == "a" and self._open_links:
            url, start, citation_id, element_id = self._open_links.pop()
            self.links.append(
                _RevisionLink(
                    url=url,
                    start=start,
                    end=self._length(),
                    citation_id=citation_id,
                    element_id=element_id,
                )
            )
        if element is not None:
            element.end = self._length()
            self._element_stack.pop()
        if was_citation and self._citation_stack:
            self._citation_stack.pop()

    def handle_data(self, data: str) -> None:
        if not data or (self._ignored_tags and self._ignored_tags[-1]):
            return
        start = self._length()
        self.pieces.append(data)
        self.parts.append(
            _TextPart(
                start=start,
                end=start + len(data),
                citation_id=self._citation_id(),
                element_id=self._element_id(),
            )
        )
        self.pieces.append(" ")

    def _length(self) -> int:
        return sum(len(piece) for piece in self.pieces)

    def _citation_id(self) -> int | None:
        return self._citation_stack[-1] if self._citation_stack else None

    def _element_id(self) -> int | None:
        return self._element_stack[-1].id if self._element_stack else None

    def result(self) -> RenderedPage:
        return RenderedPage(
            text="".join(self.pieces),
            parts=self.parts,
            elements=self.elements,
            revision_links=self.links,
        )


def rendered_page(html_text: str) -> RenderedPage:
    parser = RenderedHTML()
    parser.feed(html_text)
    return parser.result()


def _message_text(value: str) -> str:
    return " ".join(rendered_page(html.unescape(value)).text.split())


def _api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


async def _with_rate_limit_retry(
    send: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """Retry once on 429/503, waiting Retry-After capped to fit the scan deadline."""
    response = await send()
    if response.status_code in (429, 503):
        try:
            wait = float(response.headers.get("Retry-After", "1"))
        except ValueError:
            wait = 1.0
        await asyncio.sleep(min(max(wait, 0.2), RATE_LIMIT_MAX_WAIT_S))
        response = await send()
    response.raise_for_status()
    return response


async def _api_get(
    client: httpx.AsyncClient, lang: str, params: dict[str, str]
) -> httpx.Response:
    try:
        return await _with_rate_limit_retry(
            lambda: client.get(
                _api_url(lang),
                headers={"User-Agent": MEDIAWIKI_USER_AGENT},
                params=params,
                timeout=REQUEST_TIMEOUT_S,
            )
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"MediaWiki request for {lang}.wikipedia.org failed: {exc}"
        ) from exc


async def _api_post(
    client: httpx.AsyncClient, lang: str, data: dict[str, str]
) -> httpx.Response:
    try:
        return await _with_rate_limit_retry(
            lambda: client.post(
                _api_url(lang),
                headers={"User-Agent": MEDIAWIKI_USER_AGENT},
                data=data,
                timeout=REQUEST_TIMEOUT_S,
            )
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"MediaWiki request for {lang}.wikipedia.org failed: {exc}"
        ) from exc


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
        if message.content is not None and month is not None:
            text = _message_text(message.content).casefold()
            if text:
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


def _citation_id_at(page: RenderedPage, offset: int) -> int | None:
    return next(
        (part.citation_id for part in page.parts if part.start <= offset < part.end),
        None,
    )


def _element_at(page: RenderedPage, offset: int) -> _DateScope | None:
    element_id = next(
        (part.element_id for part in page.parts if part.start <= offset < part.end),
        None,
    )
    return next(
        (element for element in page.elements if element.id == element_id), None
    )


def _element_text(page: RenderedPage, element: _DateScope) -> str:
    if element.end is None:
        return ""
    return " ".join(page.text[element.start : element.end].split())


def _snippet(text: str, start: int, end: int) -> str:
    snippet = " ".join(text[max(0, start - 80) : min(len(text), end + 80)].split())
    return snippet[:160]


def _date_snippet(page: RenderedPage, start: int, end: int) -> str:
    element = _element_at(page, start)
    return (
        _element_text(page, element)
        if element is not None
        else _snippet(page.text, start, end)
    )


def page_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


def future_date_findings(
    page: RenderedPage, comparison_timestamp: datetime, months: dict[str, int], url: str
) -> list[FutureDateFinding]:
    findings: list[FutureDateFinding] = []
    for match, value in parsed_dates(page.text, months):
        if value > comparison_timestamp.date():
            findings.append(
                FutureDateFinding(
                    url=url,
                    rendered_date=match.group(0),
                    parsed_date=value,
                    revision_timestamp=comparison_timestamp,
                    snippet=_date_snippet(page, match.start(), match.end()),
                    location="reference"
                    if _citation_id_at(page, match.start()) is not None
                    else "body",
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
    client: httpx.AsyncClient, links: list[_RevisionLink], strict: bool = False
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
            if strict:
                raise
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
    client: httpx.AsyncClient,
    page: RenderedPage,
    months: dict[str, int],
    strict: bool = False,
) -> list[RevisionDateMismatchFinding]:
    links = [link for link in page.revision_links if _oldid(link.url) is not None]
    timestamps = await _revision_timestamps(client, links, strict)
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
        element = next(
            (item for item in page.elements if item.id == link.element_id), None
        )
        if element is None or element.end is None:
            continue
        dates = parsed_dates(page.text[element.start : element.end], months)
        if not dates:
            continue
        match, value = min(
            dates,
            key=lambda item: abs(element.start + item[0].start() - link.start),
        )
        if abs((value - timestamp.date()).days) > 31:
            findings.append(
                RevisionDateMismatchFinding(
                    url=link.url,
                    revid=revid,
                    rendered_date=match.group(0),
                    parsed_date=value,
                    revision_timestamp=timestamp,
                    snippet=_element_text(page, element),
                )
            )
    return findings


async def _parse_wikitext(
    client: httpx.AsyncClient, lang: str, title: str, wikitext: str
) -> RenderedPage:
    response = await _api_post(
        client,
        lang,
        {
            "action": "parse",
            "text": wikitext,
            "title": title,
            "contentmodel": "wikitext",
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
    )
    return rendered_page(
        _ParseResponse.model_validate_json(response.content).parse.text
    )


async def scan_changed_citation_dates(
    lang: str,
    title: str,
    changed_wikitexts: Sequence[str],
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> CitationDateScan:
    """Render changed citation-bearing units and report deterministic date errors."""
    if not changed_wikitexts:
        return CitationDateScan(status="skipped")
    owns_client = client is None
    mediawiki = client or httpx.AsyncClient(
        headers={"User-Agent": MEDIAWIKI_USER_AGENT}
    )
    try:
        months_task = asyncio.create_task(month_names(mediawiki, lang))
        page_tasks = [
            asyncio.create_task(_parse_wikitext(mediawiki, lang, title, text))
            for text in changed_wikitexts
        ]
        months, pages = await asyncio.gather(months_task, asyncio.gather(*page_tasks))
        comparison_timestamp = now or datetime.now(UTC)
        future = [
            finding
            for page in pages
            for finding in future_date_findings(
                page, comparison_timestamp, months, page_url(lang, title)
            )
        ]
        mismatch_lists = await asyncio.gather(
            *(
                revision_date_mismatches(mediawiki, page, months, strict=True)
                for page in pages
            )
        )
        mismatches = [finding for findings in mismatch_lists for finding in findings]
        return CitationDateScan(status="ok", findings=[*future, *mismatches])
    except Exception as exc:  # noqa: BLE001 - this escalation-only audit must fail closed
        return CitationDateScan(
            status="unavailable", error=f"{type(exc).__name__}: {exc}"
        )
    finally:
        if owns_client:
            await mediawiki.aclose()

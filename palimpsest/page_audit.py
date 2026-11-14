"""Live-page Wikipedia audit: deterministic date checks plus cited paragraph review."""

import argparse
import asyncio
import re
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

import httpx
from pydantic import BaseModel, Field

from palimpsest.citation_dates import (
    _MONTH_CACHE as _SHARED_MONTH_CACHE,
)
from palimpsest.citation_dates import (
    FutureDateFinding,
    RenderedPage,
    RevisionDateMismatchFinding,
    page_url,
    parsed_dates,
    rendered_page,
)
from palimpsest.citation_dates import (
    future_date_findings as shared_future_date_findings,
)
from palimpsest.citation_dates import (
    month_names as shared_month_names,
)
from palimpsest.citation_dates import (
    revision_date_mismatches as shared_revision_date_mismatches,
)
from palimpsest.crosslingual import (
    MEDIAWIKI_USER_AGENT,
    audit_single_language_claim,
    fetch_wikitext,
)
from palimpsest.judge import AsyncJudge
from palimpsest.pipeline import CACHE_DIR, STAGE1_CONCURRENCY
from palimpsest.reasons import REASON_TEXT, ReasonCode, reason_code
from palimpsest.schema import DisplayFlaggedSpan, FlaggedSpan, Verdict
from palimpsest.sources import SourceFetcher
from palimpsest.stage0 import extract_ref_urls, strip_wikitext
from palimpsest.stealth.models import HiddenFinding, StealthStatus
from palimpsest.stealth.scanner import reportable_findings, scan

__all__ = ("parsed_dates",)

REQUEST_TIMEOUT_S: Final = 20.0
_REF_RE: Final = re.compile(r"<ref\b", re.IGNORECASE)


class ParagraphAudit(BaseModel):
    index: int
    verdict: Verdict | None = None
    confidence: float | None = None
    reason: ReasonCode | None = None
    reason_text: str | None = None
    flagged_spans: list[DisplayFlaggedSpan] = Field(default_factory=list)
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


class _ParseResponse(BaseModel):
    parse: "_ParseResult"


class _ParseResult(BaseModel):
    text: str


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
) -> RenderedPage:
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
    return rendered_page(parsed.parse.text)


_MONTH_CACHE = _SHARED_MONTH_CACHE


async def month_names(client: httpx.AsyncClient, lang: str) -> dict[str, int]:
    """Get localized month spellings once per language for this process."""
    return await shared_month_names(client, lang)


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
                flagged_spans=[
                    DisplayFlaggedSpan(
                        **span.model_dump(),
                        context_sentence=DisplayFlaggedSpan.context_for(
                            strip_wikitext(paragraph), span.exact_substring
                        ),
                    )
                    for span in state.flagged_spans
                ],
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
        months_task = asyncio.create_task(shared_month_names(mediawiki, lang))
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
            future_dates=shared_future_date_findings(
                rendered, revision.timestamp, months, page_url(lang, title)
            ),
            revision_date_mismatches=await shared_revision_date_mismatches(
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
    findings = [
        *[
            "FUTURE_DATE "
            f"date={item.rendered_date} revision={item.revision_timestamp.isoformat()} "
            f"url={item.url} snippet={item.snippet}"
            for item in report.future_dates
        ],
        *[
            "REVISION_DATE_MISMATCH "
            f"date={item.rendered_date} revision={item.revision_timestamp.isoformat()} "
            f"url={item.url} snippet={item.snippet}"
            for item in report.revision_date_mismatches
        ],
        *[
            "paragraph "
            f"index={item.index} verdict={item.verdict} confidence={item.confidence} "
            f"reason_text={item.reason_text} "
            f"first_span={item.flagged_spans[0].exact_substring if item.flagged_spans else ''} "
            f"context_sentence={item.flagged_spans[0].context_sentence if item.flagged_spans else ''}"
            for item in report.paragraph_audits
            if item.verdict is not None and item.verdict.value.startswith("FLAG_")
        ],
    ]
    return "\n".join([_table(rows), *findings])


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

"""Cold-path cross-lingual audits grounded in each wiki's local citations."""

import asyncio
import os
import re
import time
from collections.abc import Iterable
from typing import Final, Literal

import httpx
import mwparserfromhell
from pydantic import BaseModel

from palimpsest.judge import AsyncJudge, PreparedCase, judge_with_latencies
from palimpsest.pipeline import _window_for
from palimpsest.schema import AuditOutput, Case, FlaggedSpan, SourceWindow, Verdict
from palimpsest.sources import SourceFetcher
from palimpsest.stage0 import extract_ref_urls, prefilter, strip_wikitext

# Wikimedia's User-Agent policy wants a tool name and contact URL; generic agents get 429s.
MEDIAWIKI_USER_AGENT: Final = (
    "Palimpsest/0.1 (https://github.com/Abhijay25/Palimpsest; hackathon research)"
)
DEFAULT_TARGETS: Final = ("en", "fi", "de", "fr", "es")
DEFAULT_TIMEOUT_S: Final = 15.0
_TOKEN_RE: Final = re.compile(r"[^\W\d_][\w'-]*|\d[\w'-]*", re.UNICODE)
_SENTENCE_START_RE: Final = re.compile(r"(?:^|[.!?]\s+)([^\W\d_][\w'-]*)", re.UNICODE)


class LanguageAuditState(BaseModel):
    """One target wiki's result in a cross-lingual audit."""

    lang: str
    state: Literal["AUDITED", "ABSENT", "UNAVAILABLE"]
    verdict: Verdict | None = None
    confidence: float | None = None
    latency_ms: float
    reason: str | None = None
    flagged_spans: list[FlaggedSpan] = []
    neutral_rewrite: str | None = None


class CrossLingualReport(BaseModel):
    """Cold-path audit result; it is intentionally separate from audit-diff."""

    source_lang: str
    source_title: str
    edit_verdict: Verdict
    languages: dict[str, LanguageAuditState]
    divergence_warning: bool
    reason: str
    latency_ms: float


class _LangLink(BaseModel):
    lang: str
    title: str


class _LangLinkPage(BaseModel):
    langlinks: list[_LangLink] = []


class _LangLinkQuery(BaseModel):
    pages: list[_LangLinkPage] = []


class _LangLinkResponse(BaseModel):
    query: _LangLinkQuery | None = None


class _RevisionSlot(BaseModel):
    content: str = ""


class _Revision(BaseModel):
    slots: dict[str, _RevisionSlot] = {}


class _RevisionPage(BaseModel):
    revisions: list[_Revision] = []


class _RevisionQuery(BaseModel):
    pages: list[_RevisionPage] = []


class _RevisionResponse(BaseModel):
    query: _RevisionQuery | None = None


def _api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


async def resolve_langlinks(
    client: httpx.AsyncClient, lang: str, title: str
) -> dict[str, str]:
    """Resolve a page's MediaWiki language links without a mapping database."""
    response = await client.get(
        _api_url(lang),
        headers={"User-Agent": MEDIAWIKI_USER_AGENT},
        params={
            "action": "query",
            "prop": "langlinks",
            "titles": title,
            "lllimit": "500",
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
        },
    )
    response.raise_for_status()
    parsed = _LangLinkResponse.model_validate_json(response.content)
    pages = parsed.query.pages if parsed.query is not None else []
    return {link.lang: link.title for page in pages for link in page.langlinks}


async def fetch_wikitext(client: httpx.AsyncClient, lang: str, title: str) -> str:
    """Fetch the current main-slot wikitext for a MediaWiki page."""
    response = await client.get(
        _api_url(lang),
        headers={"User-Agent": MEDIAWIKI_USER_AGENT},
        params={
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "redirects": "1",
            "rvslots": "main",
            "rvprop": "content",
            "format": "json",
            "formatversion": "2",
        },
    )
    response.raise_for_status()
    parsed = _RevisionResponse.model_validate_json(response.content)
    pages = parsed.query.pages if parsed.query is not None else []
    if not pages or not pages[0].revisions:
        return ""
    return pages[0].revisions[0].slots.get("main", _RevisionSlot()).content


def _sentence_initial_tokens(text: str) -> set[str]:
    return {match.group(1) for match in _SENTENCE_START_RE.finditer(text)}


def anchor_terms(text: str) -> set[str]:
    """Extract language-neutral paragraph-matching anchors from wikitext."""
    code = mwparserfromhell.parse(text)
    links = {
        str(link.title).strip()
        for link in code.filter_wikilinks(recursive=True)
        if str(link.title).strip()
    }
    plain = strip_wikitext(text)
    initial = _sentence_initial_tokens(plain)
    tokens = set(_TOKEN_RE.findall(plain))
    token_anchors = {
        token
        for token in tokens
        if any(char.isdigit() for char in token)
        or (token[:1].isupper() and token not in initial)
    }
    return links | token_anchors


def select_paragraphs(wikitext: str, anchors: set[str], k: int = 2) -> list[str]:
    """Return up to *k* paragraphs ranked by shared language-neutral anchors."""
    if k <= 0 or not anchors:
        return []
    minimum = 1 if len(anchors) == 1 else 2
    candidates: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(re.split(r"\n\s*\n", wikitext)):
        paragraph = paragraph.strip()
        shared = len(anchors & anchor_terms(paragraph))
        if paragraph and shared >= minimum:
            candidates.append((shared, index, paragraph))
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return [paragraph for _, _, paragraph in candidates[:k]]


async def audit_single_language_claim(
    lang: str,
    title: str,
    paragraph_wikitext: str,
    judge: AsyncJudge,
    fetcher: SourceFetcher,
) -> LanguageAuditState:
    """Audit an added local paragraph through the existing Stage 1 and 2 path."""
    started = time.perf_counter()
    plain_text = strip_wikitext(paragraph_wikitext)
    ref_urls = extract_ref_urls(paragraph_wikitext)
    case = Case(
        case_id=f"crosslingual:{lang}:{title}",
        lang=lang,
        bucket="crosslingual",
        provenance="mediawiki",
        page_title=title,
        old_text="",
        new_text=plain_text,
        ref_urls=ref_urls,
        changed_ref_urls=ref_urls,
        expected="UNLABELLED",
    )
    stage0 = prefilter(case.old_text, case.new_text, case.lang)
    window: SourceWindow = await _window_for(case, fetcher)
    prepared = PreparedCase(case=case, stage0=stage0, window=window)
    judged, _ = await judge_with_latencies(judge, [prepared])
    outcome = judged.get(case.case_id)
    if outcome is None:
        raise RuntimeError("Judge backend returned no result")
    if isinstance(outcome, str):
        raise TypeError(outcome)
    output: AuditOutput = outcome
    return LanguageAuditState(
        lang=lang,
        state="AUDITED",
        verdict=output.verdict,
        confidence=output.confidence,
        latency_ms=(time.perf_counter() - started) * 1000,
        flagged_spans=output.flagged_spans,
        neutral_rewrite=output.neutral_rewrite,
    )


def _target_languages(source_lang: str, targets: Iterable[str] | None) -> list[str]:
    if targets is None:
        configured = os.environ.get("PALIMPSEST_CROSSLINGUAL_LANGS")
        targets = configured.split(",") if configured else DEFAULT_TARGETS
    return list(dict.fromkeys(target.strip() for target in targets if target.strip()))


async def cross_lingual_fanout(
    lang: str,
    title: str,
    claim_text: str,
    edit_verdict: Verdict,
    judge: AsyncJudge,
    fetcher: SourceFetcher,
    targets: Iterable[str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: httpx.AsyncClient | None = None,
) -> CrossLingualReport:
    """Audit matching target-language paragraphs concurrently on the cold path."""
    started = time.perf_counter()
    target_languages = [
        target for target in _target_languages(lang, targets) if target != lang
    ]
    owns_client = client is None
    mediawiki = client or httpx.AsyncClient(
        headers={"User-Agent": MEDIAWIKI_USER_AGENT}
    )
    try:
        try:
            langlinks = await asyncio.wait_for(
                resolve_langlinks(mediawiki, lang, title), timeout=timeout_s
            )
        except Exception:  # noqa: BLE001 - fan-out must degrade to per-language state
            unavailable = {
                target: LanguageAuditState(
                    lang=target,
                    state="UNAVAILABLE",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    reason="Could not resolve source-language links.",
                )
                for target in target_languages
            }
            return CrossLingualReport(
                source_lang=lang,
                source_title=title,
                edit_verdict=edit_verdict,
                languages=unavailable,
                divergence_warning=False,
                reason="Language-link lookup was unavailable.",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        anchors = anchor_terms(claim_text)

        async def audit_target(target: str) -> tuple[str, LanguageAuditState]:
            target_started = time.perf_counter()
            target_title = langlinks.get(target)
            if target_title is None:
                return target, LanguageAuditState(
                    lang=target,
                    state="ABSENT",
                    latency_ms=(time.perf_counter() - target_started) * 1000,
                    reason="No language link for target wiki.",
                )
            try:
                target_wikitext = await asyncio.wait_for(
                    fetch_wikitext(mediawiki, target, target_title), timeout=timeout_s
                )
                matches = select_paragraphs(target_wikitext, anchors)
                if not matches:
                    return target, LanguageAuditState(
                        lang=target,
                        state="ABSENT",
                        latency_ms=(time.perf_counter() - target_started) * 1000,
                        reason="No paragraph shared enough language-neutral anchors.",
                    )
                audited = await asyncio.wait_for(
                    audit_single_language_claim(
                        target, target_title, matches[0], judge, fetcher
                    ),
                    timeout=timeout_s,
                )
                return target, audited.model_copy(
                    update={"latency_ms": (time.perf_counter() - target_started) * 1000}
                )
            except Exception as exc:  # noqa: BLE001 - target failure is non-fatal
                return target, LanguageAuditState(
                    lang=target,
                    state="UNAVAILABLE",
                    latency_ms=(time.perf_counter() - target_started) * 1000,
                    reason=f"{type(exc).__name__} while auditing target wiki.",
                )

        pairs = await asyncio.gather(
            *(audit_target(target) for target in target_languages)
        )
        languages = dict(pairs)
        clean_languages = [
            state.lang
            for state in languages.values()
            if state.state == "AUDITED" and state.verdict == Verdict.CLEAN_PASS
        ]
        flagged = edit_verdict.value.startswith("FLAG_")
        warning = flagged and len(clean_languages) >= 2
        reason = (
            "Flagged source edit conflicts with CLEAN_PASS audits in "
            + ", ".join(clean_languages)
            + "."
            if warning
            else "No cross-lingual epistemic divergence threshold was met."
        )
        return CrossLingualReport(
            source_lang=lang,
            source_title=title,
            edit_verdict=edit_verdict,
            languages=languages,
            divergence_warning=warning,
            reason=reason,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    finally:
        if owns_client:
            await mediawiki.aclose()

"""Deterministic evidence checks for small old-to-new value replacements."""

import asyncio
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

import httpx
from pydantic import BaseModel, Field

from palimpsest.schema import Case, Flag, FlagEvidence
from palimpsest.sources import SourceFetcher
from palimpsest.value_swaps import swaps

VALUE_CHECK_TIMEOUT_S: Final = 6.0
MAX_SWAPS_PER_UNIT: Final = 3
WIKIDATA_API: Final = "https://www.wikidata.org/w/api.php"
# Keep this in sync with crosslingual.MEDIAWIKI_USER_AGENT.  Importing that
# cold-path module would create a judge/pipeline import cycle.
MEDIAWIKI_USER_AGENT: Final = (
    "Palimpsest/0.1 (https://github.com/Abhijay25/Palimpsest; hackathon research)"
)
_OUTCOME = Literal["SUPPORTS_OLD", "SUPPORTS_NEW", "BOTH", "NEITHER"]
_SOURCE = Literal["cited", "wikidata"]
_MONTHS: Final[dict[str, int]] = {
    **{
        name: number
        for number, name in enumerate(
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
            ),
            start=1,
        )
    },
    **{
        name: number
        for number, name in enumerate(
            (
                "tammikuu",
                "helmikuu",
                "maaliskuu",
                "huhtikuu",
                "toukokuu",
                "kesäkuu",
                "heinäkuu",
                "elokuu",
                "syyskuu",
                "lokakuu",
                "marraskuu",
                "joulukuu",
            ),
            start=1,
        )
    },
    **{
        name: number
        for number, name in enumerate(
            (
                "tammikuuta",
                "helmikuuta",
                "maaliskuuta",
                "huhtikuuta",
                "toukokuuta",
                "kesäkuuta",
                "heinäkuuta",
                "elokuuta",
                "syyskuuta",
                "lokakuuta",
                "marraskuuta",
                "joulukuuta",
            ),
            start=1,
        )
    },
    **{
        name: number
        for number, name in enumerate(
            (
                "januari",
                "februari",
                "mars",
                "april",
                "maj",
                "juni",
                "juli",
                "augusti",
                "september",
                "oktober",
                "november",
                "december",
            ),
            start=1,
        )
    },
}
_DATE_NUMERIC: Final = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_DATE_ISO: Final = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_DATE_WORD: Final = re.compile(
    r"(?<!\w)(?:(\d{1,2})\.?\s+([\wåäö]+)\s+(\d{4})|([\wåäö]+)\s+(\d{1,2}),?\s+(\d{4}))(?!\w)",
    re.IGNORECASE,
)
_NUMBER: Final = re.compile(r"(?<![\w.])[-+]?\d[\d\u00a0 .,]*(?![\w.])")
_YEAR: Final = re.compile(r"(?<!\d)(\d{4})(?!\d)")


class ValueCheck(BaseModel):
    """One checked replacement and the evidence used to classify it."""

    old_value: str
    new_value: str
    outcome: _OUTCOME
    source: _SOURCE
    evidence: str | None = None
    url: str | None = None
    property_id: str | None = None


class ValueCheckReport(BaseModel):
    """Serializable collection kept on prepared evaluation cases."""

    checks: list[ValueCheck] = Field(default_factory=list)


class _DataValue(BaseModel):
    value: object


class _Snak(BaseModel):
    datavalue: _DataValue | None = None


class _Statement(BaseModel):
    mainsnak: _Snak


class _Label(BaseModel):
    value: str


class _Entity(BaseModel):
    claims: dict[str, list[_Statement]] = Field(default_factory=dict)
    labels: dict[str, _Label] = Field(default_factory=dict)


class _EntitiesResponse(BaseModel):
    entities: dict[str, _Entity] = Field(default_factory=dict)


def _fold(value: str) -> str:
    """Case- and diacritic-insensitive text used for people and place names."""
    decomposed = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .casefold()
        .split()
    )


def _date_value(value: str) -> date | None:
    """Parse full dates in ISO, dotted/slashed, and fi/sv/en month-name forms."""
    for pattern, groups in ((_DATE_ISO, (1, 2, 3)), (_DATE_NUMERIC, (3, 2, 1))):
        match = pattern.fullmatch(value.strip())
        if match is not None:
            try:
                return date(*(int(match.group(group)) for group in groups))
            except ValueError:
                return None
    match = _DATE_WORD.fullmatch(value.strip())
    if match is None:
        return None
    if match.group(1) is not None:
        day, month_name, year = match.group(1), match.group(2), match.group(3)
    else:
        month_name, day, year = match.group(4), match.group(5), match.group(6)
    month = _MONTHS.get((month_name or "").casefold())
    if month is None or day is None or year is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _number_value(value: str) -> Decimal | None:
    raw = value.strip().replace("\u00a0", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?\d[\d,.]*", raw):
        return None
    comma, period = raw.rfind(","), raw.rfind(".")
    if comma >= 0 and period >= 0:
        decimal = "," if comma > period else "."
        raw = raw.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif comma >= 0 or period >= 0:
        separator = "," if comma >= 0 else "."
        tail = raw.rsplit(separator, 1)[1]
        raw = (
            raw.replace(separator, "")
            if len(tail) == 3
            else raw.replace(separator, ".")
        )
    try:
        return Decimal(raw).normalize()
    except InvalidOperation:
        return None


def value_matches(value: str, text: str) -> bool:
    """Match a value in prose without treating format and diacritic variants as changes."""
    wanted_date = _date_value(value)
    if wanted_date is not None:
        return (
            any(
                _date_value(match.group(0)) == wanted_date
                for match in _DATE_ISO.finditer(text)
            )
            or any(
                _date_value(match.group(0)) == wanted_date
                for match in _DATE_NUMERIC.finditer(text)
            )
            or any(
                _date_value(match.group(0)) == wanted_date
                for match in _DATE_WORD.finditer(text)
            )
        )
    wanted_number = _number_value(value)
    if wanted_number is not None:
        if re.fullmatch(r"\d{4}", value.strip()):
            return any(
                match.group(1) == value.strip() for match in _YEAR.finditer(text)
            )
        return any(
            _number_value(match.group(0)) == wanted_number
            for match in _NUMBER.finditer(text)
        )
    wanted_name = _fold(value)
    return (
        bool(wanted_name)
        and re.search(rf"(?<!\w){re.escape(wanted_name)}(?!\w)", _fold(text))
        is not None
    )


def evidence_outcome(old_value: str, new_value: str, excerpts: list[str]) -> _OUTCOME:
    """Classify aggregate excerpts; a source mentioning both values remains ambiguous."""
    old_found = any(value_matches(old_value, excerpt) for excerpt in excerpts)
    new_found = any(value_matches(new_value, excerpt) for excerpt in excerpts)
    if old_found and new_found:
        return "BOTH"
    if old_found:
        return "SUPPORTS_OLD"
    if new_found:
        return "SUPPORTS_NEW"
    return "NEITHER"


def _subject(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


async def _cited_check(
    fetcher: SourceFetcher,
    urls: list[str],
    sentence: str,
    title: str,
    old: str,
    new: str,
) -> ValueCheck | None:
    excerpts: list[tuple[str, str]] = []
    for url in sorted(urls):
        queries = (sentence, f"{_subject(title)} {old}", f"{_subject(title)} {new}")
        found = await asyncio.gather(
            *(fetcher.highlights(url, query) for query in queries)
        )
        for highlights in found:
            excerpts.extend((url, quote) for quote in highlights or [])
    excerpts.sort(key=lambda excerpt: (excerpt[0], excerpt[1]))
    outcome = evidence_outcome(old, new, [quote for _, quote in excerpts])
    if outcome == "NEITHER":
        return None
    quote = next(
        (
            quote
            for _, quote in excerpts
            if value_matches(old if outcome == "SUPPORTS_OLD" else new, quote)
        ),
        excerpts[0][1] if excerpts else None,
    )
    evidence_url: str | None = next(
        (source for source, source_quote in excerpts if source_quote == quote), None
    )
    return ValueCheck(
        old_value=old,
        new_value=new,
        outcome=outcome,
        source="cited",
        evidence=quote,
        url=evidence_url,
    )


def _claim_values(
    entity: _Entity,
) -> tuple[dict[str, list[tuple[str, object]]], set[str]]:
    values: dict[str, list[tuple[str, object]]] = {}
    item_ids: set[str] = set()
    for property_id, statements in entity.claims.items():
        for statement in statements:
            datavalue = statement.mainsnak.datavalue
            if datavalue is None:
                continue
            value = datavalue.value
            values.setdefault(property_id, []).append((property_id, value))
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                item_ids.add(value["id"])
    return values, item_ids


def _time_matches(value: object, target: str) -> bool:
    if not isinstance(value, dict):
        return False
    raw, precision = value.get("time"), value.get("precision")
    if not isinstance(raw, str) or not isinstance(precision, int):
        return False
    match = re.fullmatch(r"[+-](\d{4,})-(\d{2})-(\d{2})T.*", raw)
    if match is None:
        return False
    wanted_date = _date_value(target)
    if wanted_date is not None:
        return precision >= 11 and (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ) == (wanted_date.year, wanted_date.month, wanted_date.day)
    return target.strip() == match.group(1) and precision >= 9


def _quantity_matches(value: object, target: str) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("amount"), str)
        and _number_value(value["amount"]) == _number_value(target)
    )


async def _wikidata_check(
    client: httpx.AsyncClient, lang: str, title: str, old: str, new: str
) -> ValueCheck:
    response = await client.get(
        WIKIDATA_API,
        params={
            "action": "wbgetentities",
            "sites": f"{lang}wiki",
            "titles": title,
            "props": "claims|labels",
            "languages": f"{lang}|en",
            "format": "json",
        },
    )
    response.raise_for_status()
    entity = next(
        iter(_EntitiesResponse.model_validate_json(response.content).entities.values()),
        None,
    )
    if entity is None:
        return ValueCheck(
            old_value=old,
            new_value=new,
            outcome="NEITHER",
            source="wikidata",
            url=WIKIDATA_API,
        )
    claims, item_ids = _claim_values(entity)
    labels: dict[str, str] = {}
    need_item_labels = all(
        _date_value(candidate) is None and _number_value(candidate) is None
        for candidate in (old, new)
    )
    if item_ids and need_item_labels:
        label_response = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": "|".join(sorted(item_ids)),
                "props": "labels",
                "languages": f"{lang}|en",
                "format": "json",
            },
        )
        label_response.raise_for_status()
        labels = {
            item_id: next(iter(item.labels.values())).value
            for item_id, item in _EntitiesResponse.model_validate_json(
                label_response.content
            ).entities.items()
            if item.labels
        }
    found: dict[str, tuple[str, str]] = {}
    for property_id, entries in claims.items():
        for _, value in entries:
            for candidate, key in ((old, "old"), (new, "new")):
                matched = _time_matches(value, candidate) or _quantity_matches(
                    value, candidate
                )
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    matched = matched or value_matches(
                        candidate, labels.get(value["id"], "")
                    )
                if matched and key not in found:
                    found[key] = (
                        property_id,
                        labels.get(value.get("id", ""), "")
                        if isinstance(value, dict)
                        else str(value),
                    )
    outcome: _OUTCOME = (
        "BOTH"
        if len(found) == 2
        else "SUPPORTS_OLD"
        if "old" in found
        else "SUPPORTS_NEW"
        if "new" in found
        else "NEITHER"
    )
    property_evidence = found.get("old") or found.get("new")
    matched_property_id = (
        property_evidence[0] if property_evidence is not None else None
    )
    evidence = property_evidence[1] if property_evidence is not None else None
    return ValueCheck(
        old_value=old,
        new_value=new,
        outcome=outcome,
        source="wikidata",
        evidence=evidence,
        url=WIKIDATA_API,
        property_id=matched_property_id,
    )


async def check_values(
    *,
    lang: str,
    title: str,
    old_text: str,
    new_text: str,
    ref_urls: list[str] | None,
    fetcher: SourceFetcher | None = None,
    client: httpx.AsyncClient | None = None,
    deadline_s: float = VALUE_CHECK_TIMEOUT_S,
) -> ValueCheckReport:
    """Check up to three detected pairs; errors and deadlines become NEITHER results."""
    pairs = [pair for change in swaps(old_text, new_text) for pair in change.pairs][
        :MAX_SWAPS_PER_UNIT
    ]
    if not pairs:
        return ValueCheckReport()
    own_client = client is None
    wikidata = client or httpx.AsyncClient(
        headers={"User-Agent": MEDIAWIKI_USER_AGENT}, timeout=deadline_s
    )

    async def one(old: str, new: str) -> ValueCheck:
        try:
            cited = (
                await _cited_check(fetcher, ref_urls or [], new_text, title, old, new)
                if fetcher is not None and ref_urls
                else None
            )
            if cited is not None:
                return cited
            return await _wikidata_check(wikidata, lang, title, old, new)
        except (httpx.HTTPError, ValueError):
            return ValueCheck(
                old_value=old,
                new_value=new,
                outcome="NEITHER",
                source="wikidata",
                url=WIKIDATA_API,
            )

    try:
        checks = await asyncio.wait_for(
            asyncio.gather(*(one(old, new) for old, new in pairs)), timeout=deadline_s
        )
    except TimeoutError:
        checks = [
            ValueCheck(
                old_value=old,
                new_value=new,
                outcome="NEITHER",
                source="wikidata",
                url=WIKIDATA_API,
            )
            for old, new in pairs
        ]
    finally:
        if own_client:
            await wikidata.aclose()
    return ValueCheckReport(checks=checks)


async def check_case(
    case: Case, fetcher: SourceFetcher | None = None
) -> ValueCheckReport:
    """Case-file convenience wrapper preserving the changed-reference distinction."""
    return await check_values(
        lang=case.lang,
        title=case.page_title,
        old_text=case.old_text,
        new_text=case.new_text,
        ref_urls=case.changed_ref_urls
        if case.changed_ref_urls is not None
        else case.ref_urls,
        fetcher=fetcher,
    )


def value_check_flags(checks: list[ValueCheck], new_text: str) -> list[Flag]:
    """Turn definitive old-value evidence into high-confidence administrative flags."""
    flags: list[Flag] = []
    for index, check in enumerate(checks):
        if check.outcome != "SUPPORTS_OLD":
            continue
        anchor = check.new_value if check.new_value in new_text else ""
        start = new_text.find(anchor) if anchor else None
        source = "cited" if check.source == "cited" else "wikidata"
        provenance = (
            "the cited source"
            if check.source == "cited"
            else f"Wikidata ({check.property_id or 'property'})"
        )
        flags.append(
            Flag(
                id=f"v{index}",
                kind="FACT",
                tier="admin",
                title="Changed value contradicts evidence",
                reason=f"The edit changes {check.old_value} to {check.new_value}; {provenance} gives {check.old_value}.",
                confidence=1.0,
                side="new",
                anchor_text=anchor,
                anchor_start=start,
                anchor_end=start + len(anchor) if start is not None else None,
                context_sentence=new_text,
                evidence=[
                    FlagEvidence(
                        source=source,
                        quote=check.evidence or check.old_value,
                        url=check.url,
                    )
                ],
                citations=[check.url] if check.url else [],
                neutral_rewrite=None,
                check="value_check",
            )
        )
    return flags


def suppress_supported_value_reviews(
    flags: list[Flag], checks: list[ValueCheck]
) -> list[Flag]:
    """Drop legacy VALUE_CHANGED review flags once evidence supports the edit."""
    supported_new = {
        check.new_value for check in checks if check.outcome == "SUPPORTS_NEW"
    }
    return [
        flag
        for flag in flags
        if not (
            flag.check == "judge"
            and flag.reason.startswith("VALUE_CHANGED:")
            and flag.anchor_text in supported_new
        )
    ]

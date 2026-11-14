"""Find edits whose new value disagrees with another statement on the page."""

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from urllib.parse import quote

import httpx
import mwparserfromhell
from google.genai import types
from pydantic import BaseModel, ConfigDict

from palimpsest.backends.gemini import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_JUDGE_MODEL,
    GeminiClient,
    _GeminiCaller,
)
from palimpsest.cascade import CascadeJudgeBackend
from palimpsest.citation_dates import month_names, weekday_names
from palimpsest.crosslingual import anchor_terms
from palimpsest.display_text import plain, sentences
from palimpsest.segment import EditUnit
from palimpsest.value_swaps import swaps

DEADLINE_S: Final = 6.0
MAX_SEMANTIC_CANDIDATES: Final = 5
_HEADING: Final = re.compile(r"^={2,}\s*(.*?)\s*={2,}\s*$", re.MULTILINE)
_WORD_VALUE: Final = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)


class ConsistencyAnswer(BaseModel):
    """The only model output we expose: a verbatim candidate sentence or nothing."""

    model_config = ConfigDict(extra="forbid")
    conflicting_sentence: str | None = None


@dataclass(frozen=True)
class ConsistencyFinding:
    """A page-internal disagreement safe to turn into a UI flag."""

    unit_index: int
    changed_sentence: str
    quote: str
    section: str
    method: Literal["deterministic", "semantic"]
    old_value: str
    new_value: str
    quote_in_diff: bool


class ConsistencyJudge(Protocol):
    async def __call__(
        self, changed_sentence: str, candidates: list[str]
    ) -> str | None: ...


class GeminiConsistencyJudge:
    """One Hydrogen LOW call, sharing the normal Gemini concurrency limiter."""

    _SYSTEM: Final = (
        "Compare the edited sentence with the candidate sentences from the same "
        "Wikipedia article. Return conflicting_sentence only when one candidate "
        "states a different value for the same fact. Copy that candidate exactly; "
        "otherwise return null."
    )

    def __init__(
        self,
        client: GeminiClient | None = None,
        caller: _GeminiCaller | None = None,
    ) -> None:
        # A shared caller belongs to the main judge: never change its timeout or
        # thinking level (that capped every later judge call at DEADLINE_S).
        self._caller = caller or _GeminiCaller(
            DEFAULT_JUDGE_MODEL, client, DEFAULT_BACKOFF_SECONDS
        )
        if caller is None:
            self._caller.timeout = DEADLINE_S
            self._caller.thinking = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            )

    async def __call__(
        self, changed_sentence: str, candidates: list[str]
    ) -> str | None:
        payload = json.dumps(
            {"changed_sentence": changed_sentence, "candidate_sentences": candidates},
            ensure_ascii=False,
        )
        answer, _ = await asyncio.wait_for(
            self._caller.generate(self._SYSTEM, payload, ConsistencyAnswer),
            DEADLINE_S,
        )
        if isinstance(answer, str):
            return None
        return answer.conflicting_sentence


def gemini_consistency_judge(backend: object) -> GeminiConsistencyJudge | None:
    """Reuse the primary Hydrogen caller so this pass obeys its concurrency cap."""
    from palimpsest.backends.gemini import GeminiJudgeBackend

    if isinstance(backend, GeminiJudgeBackend):
        return GeminiConsistencyJudge(caller=backend._caller)
    if isinstance(backend, CascadeJudgeBackend):
        return gemini_consistency_judge(backend.second)
    return None


@dataclass(frozen=True)
class _PageSentence:
    text: str
    section: str


@dataclass(frozen=True)
class _PageParam:
    template: str
    name: str
    value: str
    section: str


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _section_at(wikitext: str, offset: int) -> str:
    section = "Introduction"
    for match in _HEADING.finditer(wikitext):
        if match.start() > offset:
            break
        section = plain(match.group(1)) or "Introduction"
    return section


def _page_sentences(wikitext: str) -> list[_PageSentence]:
    """Visible prose sentences, retaining their nearest MediaWiki section heading."""
    result: list[_PageSentence] = []
    current = "Introduction"
    chunks = _HEADING.split(wikitext)
    # split returns prose, heading text, prose ...; plain also removes template values.
    for index, chunk in enumerate(chunks):
        if index % 2:
            current = plain(chunk) or "Introduction"
            continue
        result.extend(
            _PageSentence(sentence, current) for sentence in sentences(plain(chunk))
        )
    return result


def _params(wikitext: str) -> list[_PageParam]:
    result: list[_PageParam] = []
    for template in mwparserfromhell.parse(wikitext).filter_templates(recursive=True):
        raw = str(template)
        offset = wikitext.find(raw)
        section = _section_at(wikitext, max(offset, 0))
        name = plain(str(template.name)).casefold()
        for param in template.params:
            value = plain(str(param.value))
            if value:
                result.append(
                    _PageParam(name, plain(str(param.name)).casefold(), value, section)
                )
    return result


def _contains_value(text: str, value: str) -> bool:
    if not value:
        return False
    return (
        re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE) is not None
    )


def _temporal_pairs(
    old: str, new: str, temporal_names: dict[str, int]
) -> list[tuple[str, str]]:
    old_words = _WORD_VALUE.findall(old)
    new_words = _WORD_VALUE.findall(new)
    pairs: list[tuple[str, str]] = []
    for old_word, new_word in zip(old_words, new_words, strict=False):
        if (
            old_word.casefold() in temporal_names
            and new_word.casefold() in temporal_names
            and temporal_names[old_word.casefold()]
            != temporal_names[new_word.casefold()]
        ):
            pairs.append((old_word, new_word))
    return pairs


def _value_pairs(
    old: str, new: str, temporal_names: dict[str, int]
) -> list[tuple[str, str]]:
    found = [pair for swap in swaps(old, new) for pair in swap.pairs]
    found.extend(_temporal_pairs(old, new, temporal_names))
    return list(dict.fromkeys(found))


def _old_param_matches(
    param: _PageParam, old_params: Sequence[_PageParam], old_value: str
) -> bool:
    return any(
        old.template == param.template
        and old.name == param.name
        and _normalise(old.value) == _normalise(old_value)
        for old in old_params
    )


def _outside_changed(candidate: str, changed: str) -> bool:
    return _normalise(candidate) != _normalise(changed)


def article_url(lang: str, title: str, section: str) -> str:
    """Build the article jump URL with MediaWiki's underscore fragment convention."""
    page = quote(title.replace(" ", "_"), safe="")
    fragment = quote(section.replace(" ", "_"), safe="")
    return f"https://{lang}.wikipedia.org/wiki/{page}#{fragment}"


async def _localized_temporal_names(
    client: httpx.AsyncClient, lang: str
) -> dict[str, int]:
    months, weekdays = await asyncio.gather(
        month_names(client, lang), weekday_names(client, lang)
    )
    # Distinct ranges prevent a Wednesday-to-March replacement looking unchanged.
    return {**months, **{name: value + 100 for name, value in weekdays.items()}}


async def check_page_consistency(
    old_wikitext: str,
    new_wikitext: str,
    units: Sequence[EditUnit],
    lang: str,
    judge: ConsistencyJudge | None = None,
    client: httpx.AsyncClient | None = None,
    deadline_s: float = DEADLINE_S,
) -> list[ConsistencyFinding]:
    """Best-effort page consistency scan; any timeout or remote error yields no finding."""
    if not units or old_wikitext == new_wikitext:
        return []
    owns_client = client is None
    mediawiki = client or httpx.AsyncClient()
    started = asyncio.get_running_loop().time()
    try:
        try:
            temporal_names = await asyncio.wait_for(
                _localized_temporal_names(mediawiki, lang), timeout=deadline_s
            )
        except Exception:  # noqa: BLE001 - locale lookup must never hold up an edit audit
            temporal_names = {}
        page_sentences = _page_sentences(new_wikitext)
        new_params = _params(new_wikitext)
        old_params = _params(old_wikitext)
        findings: list[ConsistencyFinding] = []
        for unit in units:
            remaining = deadline_s - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                break
            changed = plain(unit.new_text)
            if not changed:
                continue
            changed_sentence = sentences(changed)[0] if sentences(changed) else changed
            pairs = _value_pairs(unit.old_text, unit.new_text, temporal_names)
            if not pairs:
                continue
            anchors = anchor_terms(unit.new_text)
            deterministic: ConsistencyFinding | None = None
            for old_value, new_value in pairs:
                for candidate in page_sentences:
                    if (
                        _outside_changed(candidate.text, changed_sentence)
                        and _contains_value(candidate.text, old_value)
                        and bool(anchors & anchor_terms(candidate.text))
                    ):
                        deterministic = ConsistencyFinding(
                            unit.index,
                            changed_sentence,
                            candidate.text,
                            candidate.section,
                            "deterministic",
                            old_value,
                            new_value,
                            _normalise(candidate.text) in _normalise(changed),
                        )
                        break
                if deterministic is None:
                    for param in new_params:
                        if _contains_value(param.value, old_value) and (
                            bool(anchors & anchor_terms(param.value))
                            or _old_param_matches(param, old_params, old_value)
                        ):
                            deterministic = ConsistencyFinding(
                                unit.index,
                                changed_sentence,
                                param.value,
                                param.section,
                                "deterministic",
                                old_value,
                                new_value,
                                _normalise(param.value) in _normalise(changed),
                            )
                            break
                if deterministic is not None:
                    break
            if deterministic is not None:
                findings.append(deterministic)
                continue
            if judge is None:
                continue
            ranked_candidates = [
                (len(anchors & anchor_terms(candidate.text)), index, candidate)
                for index, candidate in enumerate(page_sentences)
                if _outside_changed(candidate.text, changed_sentence)
                and len(anchors & anchor_terms(candidate.text)) >= 2
            ]
            ranked_candidates.sort(key=lambda item: (-item[0], item[1]))
            candidates = [
                candidate
                for _, _, candidate in ranked_candidates[:MAX_SEMANTIC_CANDIDATES]
            ]
            if not candidates:
                continue
            try:
                quote = await asyncio.wait_for(
                    judge(
                        changed_sentence, [candidate.text for candidate in candidates]
                    ),
                    timeout=remaining,
                )
            except Exception:  # noqa: BLE001 - semantic pass is strictly optional
                quote = None
            normal_quote = _normalise(quote or "")
            matched = next(
                (
                    candidate
                    for candidate in candidates
                    if _normalise(candidate.text) == normal_quote
                ),
                None,
            )
            if matched is not None:
                old_value, new_value = pairs[0]
                findings.append(
                    ConsistencyFinding(
                        unit.index,
                        changed_sentence,
                        matched.text,
                        matched.section,
                        "semantic",
                        old_value,
                        new_value,
                        _normalise(matched.text) in _normalise(changed),
                    )
                )
        return findings
    finally:
        if owns_client:
            await mediawiki.aclose()

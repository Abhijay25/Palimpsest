"""Bounded whole-page internal-consistency candidates and adjudication."""

import asyncio
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from palimpsest.backends.gemini import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_JUDGE_MODEL,
    GeminiClient,
    _GeminiCaller,
    _env_number,
)
from palimpsest.display_text import plain

DEADLINE_S: Final = 45.0
MAX_GROUPS: Final = 40
_HEADING: Final = re.compile(r"^={2,}\s*(.*?)\s*={2,}\s*$", re.MULTILINE)
_WORD: Final = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)
_PROPER_NAME: Final = re.compile(
    r"\b[A-ZÅÄÖ][\w'-]*(?:\s+[A-ZÅÄÖ][\w'-]*)*\b", re.UNICODE
)
_NUMBER: Final = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}|"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|tammikuu(?:ta)?|helmikuu(?:ta)?|maaliskuu(?:ta)?|"
    r"huhtikuu(?:ta)?|toukokuu(?:ta)?|kesäkuu(?:ta)?|heinäkuu(?:ta)?|elokuu(?:ta)?|"
    r"syyskuu(?:ta)?|lokakuu(?:ta)?|marraskuu(?:ta)?|joulukuu(?:ta)?|januari|februari|"
    r"mars|april|maj|juni|juli|augusti|september|oktober|november|december)\s+\d{4}|"
    r"\d[\d\u00a0 ,.]*(?:%|km|kilomet(?:er|re|ri[äa])|m|met(?:er|re|ri[äa])|"
    r"kg|kilogram(?:me|maa)?|mi|mile(?:s)?|ft|feet|years?|vuotta|år)?|"
    r"(?:first|second|third|fourth|fifth|ensimm(?:äinen|ainen)|toinen|kolmas|"
    r"första|andra|tredje))\b",
    re.IGNORECASE,
)
_STOPWORDS: Final = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "with",
        "this",
        "these",
        "those",
        "founded",
        "born",
        "died",
        "history",
        "section",
        "article",
        "ja",
        "on",
        "oli",
        "ovat",
        "että",
        "se",
        "sen",
        "sekä",
        "tai",
        "mutta",
        "kuin",
        "myös",
        "vuonna",
        "och",
        "att",
        "det",
        "den",
        "som",
        "en",
        "ett",
        "på",
        "i",
        "av",
        "till",
        "med",
        "för",
        "är",
        "var",
    ]
)


@dataclass(frozen=True)
class PageSentence:
    """A visible sentence with a stable page-order position and section."""

    text: str
    section: str
    position: int


@dataclass(frozen=True)
class CandidateGroup:
    """Two claims with overlapping entity/event terms and incompatible values."""

    group_id: str
    first: PageSentence
    second: PageSentence
    first_values: tuple[str, ...]
    second_values: tuple[str, ...]
    keywords: tuple[str, ...]


class PageConsistencyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    conflict: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=240)


class PageConsistencyAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[PageConsistencyDecision]


class PageConsistencyJudge(Protocol):
    async def __call__(
        self, groups: Sequence[CandidateGroup]
    ) -> list[PageConsistencyDecision]: ...


class GeminiPageConsistencyJudge:
    """One Hydrogen LOW request for a fixed, pre-filtered batch of candidates."""

    _SYSTEM: Final = (
        "Assess only the supplied pairs of sentences from one Wikipedia page. For each "
        "group, say conflict=true only if they state incompatible values for the same "
        "event or entity. Different events (including a person's birth and death) are "
        "not conflicts. Return every group_id exactly once with a 0..1 confidence and "
        "a neutral one-line reason."
    )

    def __init__(
        self,
        client: GeminiClient | None = None,
        caller: _GeminiCaller | None = None,
    ) -> None:
        self.deadline = min(
            75.0, _env_number("PALIMPSEST_PAGE_TIMEOUT_SECONDS", DEADLINE_S)
        )
        self._caller = caller or _GeminiCaller(
            os.environ.get("GEMINI_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL,
            client,
            DEFAULT_BACKOFF_SECONDS,
        )
        if caller is None:
            self._caller.timeout = self.deadline
            self._caller.thinking = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            )

    async def __call__(
        self, groups: Sequence[CandidateGroup]
    ) -> list[PageConsistencyDecision]:
        payload = {
            "groups": [
                {
                    "group_id": group.group_id,
                    "first_sentence": group.first.text,
                    "first_section": group.first.section,
                    "first_values": group.first_values,
                    "second_sentence": group.second.text,
                    "second_section": group.second.section,
                    "second_values": group.second_values,
                    "shared_keywords": group.keywords,
                }
                for group in groups
            ]
        }
        answer, _ = await asyncio.wait_for(
            self._caller.generate(
                self._SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                PageConsistencyAnswers,
            ),
            self.deadline,
        )
        if isinstance(answer, str):
            raise TypeError(answer)
        expected = {group.group_id for group in groups}
        by_id = {
            item.group_id: item for item in answer.answers if item.group_id in expected
        }
        if set(by_id) != expected:
            raise TypeError("Gemini returned incomplete page-consistency decisions")
        return [by_id[group.group_id] for group in groups]


def _page_sentences(wikitext: str) -> list[PageSentence]:
    result: list[PageSentence] = []
    current_section = "Introduction"
    cursor = 0
    for match in _HEADING.finditer(wikitext):
        result.extend(
            _sentences_in(wikitext[cursor : match.start()], current_section, cursor)
        )
        current_section = plain(match.group(1)) or "Introduction"
        cursor = match.end()
    result.extend(_sentences_in(wikitext[cursor:], current_section, cursor))
    return result


def _sentences_in(
    source: str, section: str, source_position: int
) -> list[PageSentence]:
    visible = plain(source)
    result: list[PageSentence] = []
    start = 0
    for index, character in enumerate(visible):
        if character not in ".!?":
            continue
        next_index = index + 1
        while next_index < len(visible) and visible[next_index].isspace():
            next_index += 1
        # A full stop in dates such as "1. tammikuuta" is not a boundary.
        if (
            character == "."
            and next_index < len(visible)
            and visible[next_index].islower()
        ):
            continue
        if next_index < len(visible) and not visible[index + 1].isspace():
            continue
        sentence = visible[start : index + 1].strip()
        if sentence:
            result.append(PageSentence(sentence, section, source_position + start))
        start = index + 1
    tail = visible[start:].strip()
    if tail:
        result.append(PageSentence(tail, section, source_position + start))
    return result


def _values(text: str) -> tuple[str, ...]:
    numeric = [match.group().casefold() for match in _NUMBER.finditer(text)]
    named: list[str] = []
    for match in _PROPER_NAME.finditer(text):
        words = match.group().split()
        # A capital at sentence start is normally grammar, not an entity value.
        if len(words) == 1 and match.start() == 0:
            continue
        while words and words[0].casefold() in _STOPWORDS:
            words.pop(0)
        if words:
            named.append(" ".join(words).casefold())
    return tuple(dict.fromkeys([*numeric, *named]))


def _keywords(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(_NUMBER.sub(" ", text))
        if len(token) >= 2 and token.casefold() not in _STOPWORDS
    }


def _predicate_keywords(text: str) -> set[str]:
    """Non-name terms shared by both claims, avoiding born-versus-died matches."""
    without_values = _NUMBER.sub(" ", text)
    return {
        token.casefold()
        for token in _WORD.findall(without_values)
        if token == token.lower()
        and len(token) >= 2
        and token.casefold() not in _STOPWORDS
    }


def candidate_groups(
    wikitext: str, max_groups: int = MAX_GROUPS
) -> list[CandidateGroup]:
    """Deterministically find value-conflicting same-event sentence pairs.

    This intentionally has no language service: short EN/FI/SV stopword handling and
    Unicode token overlap keep it predictable when an audit is run offline.
    """
    indexed: list[tuple[PageSentence, tuple[str, ...], set[str]]] = []
    seen: set[tuple[frozenset[str], tuple[str, ...]]] = set()
    for sentence in _page_sentences(wikitext):
        values = _values(sentence.text)
        if not values:
            continue
        words = _keywords(sentence.text)
        # Repeated identical claims cannot introduce a new internal conflict.
        signature = (frozenset(words), values)
        if signature in seen:
            continue
        seen.add(signature)
        indexed.append((sentence, values, words))
    groups: list[CandidateGroup] = []
    for first_index, (first, first_values, first_words) in enumerate(indexed):
        for second, second_values, second_words in indexed[first_index + 1 :]:
            shared = first_words & second_words
            if (
                len(shared) < 2
                or not (
                    _predicate_keywords(first.text) & _predicate_keywords(second.text)
                )
                or first_values == second_values
            ):
                continue
            # A shared date/number is often an identifier rather than a conflict;
            # require at least one distinct value on each side.
            if not set(first_values) - set(second_values) or not set(
                second_values
            ) - set(first_values):
                continue
            groups.append(
                CandidateGroup(
                    group_id=f"g{len(groups):03d}",
                    first=first,
                    second=second,
                    first_values=first_values,
                    second_values=second_values,
                    keywords=tuple(sorted(shared)),
                )
            )
            if len(groups) >= max_groups:
                return groups
    return groups


async def adjudicate_page(
    wikitext: str, judge: PageConsistencyJudge
) -> tuple[list[CandidateGroup], list[PageConsistencyDecision]]:
    """Generate at most forty candidates, then make exactly one model call."""
    groups = candidate_groups(wikitext)
    if not groups:
        return groups, []
    return groups, await judge(groups)

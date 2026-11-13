"""Stage 0: deterministic pre-filter. Conservative: unsure means NOT clean."""

import re
import time
from collections import Counter
from typing import Literal

import mwparserfromhell
from pydantic import BaseModel

from palimpsest.wordlists import WATCH_LISTS, WordList

_URL_RE = re.compile(r"https?://[^\s|\]<>}\"']+")
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_MAX_TYPO_DISTANCE = 2
_MIN_TYPO_LENGTH = 4


class Stage0Result(BaseModel):
    clean: bool
    reasons: list[str]
    latency_ms: float


def _parse(wikitext: str) -> mwparserfromhell.wikicode.Wikicode:
    return mwparserfromhell.parse(wikitext)


def _ref_tags(
    code: mwparserfromhell.wikicode.Wikicode,
) -> list[mwparserfromhell.nodes.Tag]:
    return [
        t
        for t in code.filter_tags(recursive=True)
        if str(t.tag).strip().lower() == "ref"
    ]


def extract_ref_urls(wikitext: str) -> list[str]:
    """URLs found inside <ref> tags, in order, deduplicated."""
    urls: list[str] = []
    for tag in _ref_tags(_parse(wikitext)):
        if tag.contents is None:
            continue
        for url in _URL_RE.findall(str(tag.contents)):
            cleaned = url.rstrip(".,;)")
            if cleaned not in urls:
                urls.append(cleaned)
    return urls


def strip_wikitext(wikitext: str) -> str:
    """Plain text with <ref> tags removed and markup stripped."""
    code = _parse(wikitext)
    for tag in _ref_tags(code):
        try:
            code.remove(tag)
        except ValueError:
            continue
    return str(code.strip_code(normalize=True, collapse=True))


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower().replace("’", "'"))


def _non_ref_templates(wikitext: str) -> list[str]:
    code = _parse(wikitext)
    for tag in _ref_tags(code):
        try:
            code.remove(tag)
        except ValueError:
            continue
    return [
        re.sub(r"\s+", " ", str(t)).strip().lower() for t in code.filter_templates()
    ]


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def _token_hits(token: str, words: WordList) -> bool:
    return token in words.exact or any(token.startswith(p) for p in words.prefixes)


def _phrase_delta(old: str, new: str, words: WordList) -> list[str]:
    return [p for p in words.phrases if old.count(p) != new.count(p)]


def _watch_reasons(
    old_tokens: list[str], new_tokens: list[str], lang: Literal["en", "fi"]
) -> list[str]:
    old_counts, new_counts = Counter(old_tokens), Counter(new_tokens)
    changed = list((old_counts - new_counts).elements()) + list(
        (new_counts - old_counts).elements()
    )
    old_joined, new_joined = " ".join(old_tokens), " ".join(new_tokens)
    reasons: list[str] = []
    for category, words in WATCH_LISTS[lang].items():
        hits = sorted({t for t in changed if _token_hits(t, words)})
        hits += _phrase_delta(old_joined, new_joined, words)
        if hits:
            reasons.append(f"{category}: {', '.join(hits)}")
    return reasons


def _is_single_typo(old_tokens: list[str], new_tokens: list[str]) -> bool:
    if len(old_tokens) != len(new_tokens):
        return False
    diffs = [(a, b) for a, b in zip(old_tokens, new_tokens, strict=True) if a != b]
    if len(diffs) != 1:
        return False
    a, b = diffs[0]
    return (
        min(len(a), len(b)) >= _MIN_TYPO_LENGTH
        and not any(c.isdigit() for c in a + b)
        and _levenshtein(a, b) <= _MAX_TYPO_DISTANCE
    )


def prefilter(old_text: str, new_text: str, lang: Literal["en", "fi"]) -> Stage0Result:
    start = time.perf_counter()
    reasons: list[str] = []

    old_tokens = _tokens(strip_wikitext(old_text))
    new_tokens = _tokens(strip_wikitext(new_text))

    if not old_tokens or not new_tokens:
        reasons.append("empty side (pure insertion or deletion)")
    if set(extract_ref_urls(old_text)) != set(extract_ref_urls(new_text)):
        reasons.append("ref url set changed")
    if _non_ref_templates(old_text) != _non_ref_templates(new_text):
        reasons.append("template changed")

    if old_tokens != new_tokens:
        if any(c.isdigit() for t in set(old_tokens) ^ set(new_tokens) for c in t):
            reasons.append("number changed")
        reasons.extend(_watch_reasons(old_tokens, new_tokens, lang))
        if not reasons and not _is_single_typo(old_tokens, new_tokens):
            reasons.append("token change beyond single typo")

    return Stage0Result(
        clean=not reasons,
        reasons=reasons,
        latency_ms=(time.perf_counter() - start) * 1000,
    )

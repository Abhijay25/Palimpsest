"""Stage 0: deterministic pre-filter. Conservative: unsure means NOT clean."""

import difflib
import re
import time
from collections import Counter

import mwparserfromhell
from pydantic import BaseModel

from palimpsest.wordlists import WATCH_LISTS, WordList

_URL_RE = re.compile(r"https?://[^\s|\]<>}\"']+")
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_REF_RE = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_REF_NAME_RE = re.compile(r"""\bname\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>"']+))""")
_REF_PLACEHOLDER = "\ue000{}\ue001"
_SENTENCE_END_RE = re.compile(r"[.!?](?:\ue000\d+\ue001)*\s+")
_PLACEHOLDER_RE = re.compile(r"\ue000(\d+)\ue001")
_MAX_TYPO_DISTANCE = 2
_TYPO_RELATIVE_DISTANCE = 0.25
_MAX_TYPO_LENGTH_DIFF = 2
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


def _ref_name(ref: str) -> str | None:
    match = _REF_NAME_RE.search(ref[: ref.index(">") + 1])
    return next((g for g in match.groups() if g), None) if match else None


def _sentences_with_refs(wikitext: str) -> list[tuple[str, list[str]]]:
    """Sentences as (stripped text, raw ref tags); a ref belongs to the sentence it sits in or follows."""
    refs: list[str] = []

    def stash(match: re.Match[str]) -> str:
        refs.append(match.group(0))
        return _REF_PLACEHOLDER.format(len(refs) - 1)

    masked = _REF_RE.sub(stash, wikitext)
    pieces: list[str] = []
    start = 0
    for end in _SENTENCE_END_RE.finditer(masked):
        pieces.append(masked[start : end.end()])
        start = end.end()
    pieces.append(masked[start:])
    result: list[tuple[str, list[str]]] = []
    for piece in pieces:
        own = [refs[int(i)] for i in _PLACEHOLDER_RE.findall(piece)]
        plain = " ".join(strip_wikitext(_PLACEHOLDER_RE.sub("", piece)).split())
        if plain:
            result.append((plain, own))
    return result


def refs_for_changed_sentences(old_wikitext: str, new_wikitext: str) -> list[str]:
    """URLs of refs attached to sentences of new_wikitext whose text is absent from old_wikitext."""
    old_plain = {plain for plain, _ in _sentences_with_refs(old_wikitext)}
    named: dict[str, list[str]] = {}
    for ref in _REF_RE.findall(new_wikitext):
        name = _ref_name(ref)
        if name is not None and not ref.rstrip().endswith("/>"):
            named[name] = [u.rstrip(".,;)") for u in _URL_RE.findall(ref)]
    urls: list[str] = []
    for plain, refs in _sentences_with_refs(new_wikitext):
        if plain in old_plain:
            continue
        for ref in refs:
            if ref.rstrip().endswith("/>"):
                name = _ref_name(ref)
                found = named.get(name, []) if name is not None else []
            else:
                found = [u.rstrip(".,;)") for u in _URL_RE.findall(ref)]
            for url in found:
                if url not in urls:
                    urls.append(url)
    return urls


_CITATION_RE = re.compile(r"<ref\b|\{\{\s*(?:cite|sfn)", re.IGNORECASE)


def changed_region_has_citation(old_wikitext: str, new_wikitext: str) -> bool:
    """True when words inserted or replaced in new_wikitext include a ref tag or cite/sfn template."""
    old_words = old_wikitext.split()
    new_words = new_wikitext.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    return any(
        _CITATION_RE.search(" ".join(new_words[j1:j2]))
        for tag, _, _, j1, j2 in matcher.get_opcodes()
        if tag in ("insert", "replace")
    )


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
    old_tokens: list[str], new_tokens: list[str], lang: str
) -> list[str]:
    old_counts, new_counts = Counter(old_tokens), Counter(new_tokens)
    changed = list((old_counts - new_counts).elements()) + list(
        (new_counts - old_counts).elements()
    )
    old_joined, new_joined = " ".join(old_tokens), " ".join(new_tokens)
    reasons: list[str] = []
    for category, words in WATCH_LISTS.get(lang, {}).items():
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
        and a[0] == b[0]
        and abs(len(a) - len(b)) <= _MAX_TYPO_LENGTH_DIFF
        and _levenshtein(a, b)
        <= max(_MAX_TYPO_DISTANCE, round(_TYPO_RELATIVE_DISTANCE * max(len(a), len(b))))
    )


def prefilter(old_text: str, new_text: str, lang: str) -> Stage0Result:
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

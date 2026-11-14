"""Stage 0: deterministic pre-filter. Conservative: unsure means NOT clean."""

import re
import time
from collections import Counter
from dataclasses import dataclass

import mwparserfromhell
from pydantic import BaseModel

from palimpsest.wordlists import WATCH_LISTS, WordList

_URL_RE = re.compile(r"https?://[^\s|\]<>}\"']+")
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_REF_RE = re.compile(
    r"<ref\b[^>]*?/\s*>|<ref\b[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE
)
_CITATION_MARKUP_RE = re.compile(
    r"<ref\b[^>]*?/\s*>|<ref\b[^>]*>.*?</ref>|"
    r"\{\{\s*(?:cite|citation|sfn)\b(?:[^{}]|\{[^{}]*\})*\}\}",
    re.DOTALL | re.IGNORECASE,
)
_REF_NAME_RE = re.compile(r"""\bname\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>"']+))""")
_REF_PLACEHOLDER = "\ue000{}\ue001"
_SENTENCE_END_RE = re.compile(r"(?<!\b[A-ZÅÄÖ])[.!?](?:\ue000\d+\ue001)*\s+")
_PLACEHOLDER_RE = re.compile(r"\ue000(\d+)\ue001")
_MAX_TYPO_DISTANCE = 2
_TYPO_RELATIVE_DISTANCE = 0.25
_MAX_TYPO_LENGTH_DIFF = 2
_MIN_TYPO_LENGTH = 4


class Stage0Result(BaseModel):
    clean: bool
    reasons: list[str]
    latency_ms: float


@dataclass(frozen=True)
class RemovalSummary:
    """Deterministic evidence for a deletion that needs separate routing."""

    old_plain_size: int
    new_plain_size: int
    removed_plain_size: int
    removed_cited_sentences: list[str]

    @property
    def most_of_page_removed(self) -> bool:
        return self.old_plain_size > 0 and (
            self.new_plain_size == 0
            or self.removed_plain_size * 2 >= self.old_plain_size
        )

    @property
    def has_multiple_cited_removals(self) -> bool:
        return len(self.removed_cited_sentences) >= 2


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


def _is_reused_ref(ref: str) -> bool:
    """Whether a ref tag is a self-closing reference reuse."""
    return bool(re.search(r"/\s*>\s*$", ref))


def _sentences_with_refs(wikitext: str) -> list[tuple[str, list[str]]]:
    """Sentences as (stripped text, raw ref tags); a ref belongs to the sentence it sits in or follows."""
    return _sentences_with_markup(wikitext, _REF_RE)


def _sentences_with_markup(
    wikitext: str, markup: re.Pattern[str]
) -> list[tuple[str, list[str]]]:
    """Sentences paired with citation markup they contain or that directly follows."""
    refs: list[str] = []

    def stash(match: re.Match[str]) -> str:
        refs.append(match.group(0))
        return _REF_PLACEHOLDER.format(len(refs) - 1)

    masked = markup.sub(stash, wikitext)
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


def _deleted_sentence_indexes(old: list[str], new: list[str]) -> list[int]:
    """Indexes of sentences deleted outright, excluding sentence replacements."""
    import difflib

    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return [
        index
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag == "delete" or (tag == "replace" and j1 == j2)
        for index in range(i1, i2)
    ]


def removal_summary(old_wikitext: str, new_wikitext: str) -> RemovalSummary:
    """Describe plain-text loss and cited sentences deleted without replacement."""
    old_plain = strip_wikitext(old_wikitext)
    new_plain = strip_wikitext(new_wikitext)
    old_sentences = _sentences_with_refs(old_wikitext)
    new_sentences = _sentences_with_refs(new_wikitext)
    old_keys = [" ".join(sentence.split()) for sentence, _ in old_sentences]
    new_keys = [" ".join(sentence.split()) for sentence, _ in new_sentences]
    removed_cited_sentences = [
        old_sentences[index][0]
        for index in _deleted_sentence_indexes(old_keys, new_keys)
        if old_sentences[index][1]
    ]
    return RemovalSummary(
        old_plain_size=len(old_plain),
        new_plain_size=len(new_plain),
        removed_plain_size=max(len(old_plain) - len(new_plain), 0),
        removed_cited_sentences=removed_cited_sentences,
    )


def changed_claim_has_added_citation(
    old_wikitext: str, new_wikitext: str, claim: str
) -> bool:
    """Whether a changed claim's sentence carries citation markup added by the edit.

    Citation markup immediately after a sentence belongs to that sentence, including
    named-ref reuse such as a count reference whose definition is elsewhere.
    """
    normalised_claim = " ".join(strip_wikitext(claim).split()).casefold()
    if not normalised_claim:
        return False
    return any(
        normalised_claim in " ".join(sentence.split()).casefold()
        for sentence in _changed_sentences_with_added_citation(
            old_wikitext, new_wikitext
        )
    )


def _changed_sentences_with_added_citation(
    old_wikitext: str, new_wikitext: str
) -> list[str]:
    """Return changed sentences that carry citation markup newly added by the edit."""
    old_sentences = {
        sentence
        for sentence, _ in _sentences_with_markup(old_wikitext, _CITATION_MARKUP_RE)
    }
    old_markup = Counter(_CITATION_MARKUP_RE.findall(old_wikitext))
    sourced: list[str] = []
    for sentence, markup in _sentences_with_markup(new_wikitext, _CITATION_MARKUP_RE):
        added_markup: list[str] = []
        for item in markup:
            if old_markup[item]:
                old_markup[item] -= 1
            else:
                added_markup.append(item)
        if sentence not in old_sentences and added_markup:
            sourced.append(sentence)
    return sourced


def refs_for_changed_sentences(
    old_wikitext: str,
    new_wikitext: str,
    reference_wikitext: str | None = None,
) -> list[str]:
    """URLs attached to changed sentences, resolving named refs from the new page.

    ``new_wikitext`` can be an edit unit while a named-ref definition is elsewhere
    in the revision (for example, in ``{{Viitteet|refs=...}}``).  Supplying that
    complete revision as ``reference_wikitext`` preserves the sentence-local
    citation association without treating every page reference as changed.
    """
    old_sentences = _sentences_with_refs(old_wikitext)
    new_sentences = _sentences_with_refs(new_wikitext)
    old_plain = {plain for plain, _ in old_sentences}

    def named_refs(wikitext: str) -> dict[str, list[str]]:
        named: dict[str, list[str]] = {}
        for ref in _REF_RE.findall(wikitext):
            name = _ref_name(ref)
            if name is not None and not _is_reused_ref(ref):
                named[name] = [u.rstrip(".,;)") for u in _URL_RE.findall(ref)]
        return named

    new_named = named_refs(reference_wikitext or new_wikitext)
    old_named = named_refs(old_wikitext)

    def add_urls(refs: list[str], named: dict[str, list[str]], urls: list[str]) -> None:
        for ref in refs:
            if _is_reused_ref(ref):
                name = _ref_name(ref)
                found = named.get(name, []) if name is not None else []
            else:
                found = [u.rstrip(".,;)") for u in _URL_RE.findall(ref)]
            for url in found:
                if url not in urls:
                    urls.append(url)

    urls: list[str] = []
    for plain, refs in new_sentences:
        if plain in old_plain:
            continue
        add_urls(refs, new_named, urls)
    for index in _deleted_sentence_indexes(
        [" ".join(sentence.split()) for sentence, _ in old_sentences],
        [" ".join(sentence.split()) for sentence, _ in new_sentences],
    ):
        add_urls(old_sentences[index][1], old_named, urls)
    return urls


def changed_region_has_citation(old_wikitext: str, new_wikitext: str) -> bool:
    """True when a changed sentence carries citation markup newly added by the edit."""
    return bool(_changed_sentences_with_added_citation(old_wikitext, new_wikitext))


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

"""Turn wikitext fragments into short plain text an admin can read at a glance."""

import difflib
import re
from typing import Final

_REF_BLOCK: Final = re.compile(r"<ref\b[^>/]*>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
_REF_SELF: Final = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
_TAG: Final = re.compile(r"<[^>]+>")
_LINK: Final = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_EXT_LINK: Final = re.compile(r"\[(?:https?:)?//\S+\s+([^\]]+)\]")
_BARE_EXT_LINK: Final = re.compile(r"\[(?:https?:)?//[^\]\s]+\]")
_QUOTES: Final = re.compile(r"'{2,}")
_SPACE: Final = re.compile(r"\s+")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+(?=\S)")
DEFAULT_MAX_CHARS: Final = 240


def _strip_templates(text: str) -> str:
    """Remove {{...}} including nested templates; unbalanced braces are left as is."""
    out: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}" and depth:
            depth -= 1
            i += 2
            continue
        if not depth:
            out.append(text[i])
        i += 1
    return "".join(out)


def plain(wikitext: str) -> str:
    """Readable text: no refs, templates, link markup, bold/italic quotes or tags."""
    text = _REF_BLOCK.sub("", wikitext)
    text = _REF_SELF.sub("", text)
    text = _strip_templates(text)
    text = _LINK.sub(r"\1", text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _BARE_EXT_LINK.sub("", text)
    text = _QUOTES.sub("", text)
    text = _TAG.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def shorten(text: str, max_chars: int = DEFAULT_MAX_CHARS, focus: str = "") -> str:
    """Cut text to max_chars around focus (or from the start), marking cuts with an ellipsis."""
    if len(text) <= max_chars:
        return text
    at = text.find(focus) if focus else -1
    if at < 0:
        return text[: max_chars - 1].rstrip() + "…"
    start = max(0, min(at - max_chars // 3, len(text) - max_chars))
    piece = text[start : start + max_chars].strip()
    return (
        ("…" if start > 0 else "")
        + piece
        + ("…" if start + max_chars < len(text) else "")
    )


def sentence_with(text: str, anchor: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """The plain sentence of text that contains anchor (plain), shortened around it."""
    plain_text = plain(text)
    plain_anchor = plain(anchor) or anchor
    for sentence in sentences(plain_text):
        if plain_anchor and plain_anchor in sentence:
            return shorten(sentence, max_chars, plain_anchor)
    return shorten(plain_text, max_chars, plain_anchor)


def matching_sentence(
    text: str, reference: str, max_chars: int = DEFAULT_MAX_CHARS
) -> str | None:
    """The plain sentence of text most similar to reference, or None if nothing is close."""
    candidates = sentences(plain(text))
    if not candidates or not reference:
        return None
    best = max(
        candidates,
        key=lambda s: difflib.SequenceMatcher(None, s, reference).ratio(),
    )
    if difflib.SequenceMatcher(None, best, reference).ratio() < 0.4:
        return None
    return shorten(best, max_chars)

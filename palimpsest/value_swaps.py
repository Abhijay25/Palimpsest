"""Deterministic detection of values replaced in an edit."""

import difflib
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\d[\d.,]*|[A-ZÅÄÖ][\w'-]+(?:\s[A-ZÅÄÖ][\w'-]+)*")
_NUMBER = re.compile(r"\d[\d.,]*")


def _norm(value: str) -> str:
    """Remove presentation punctuation which is not part of a value."""
    value = value.strip("()[]{}\"'“”«»|=").rstrip(".,;:")
    return re.sub(r"['’]s$", "", value)


def _values(words: list[str], starts_sentence: bool) -> list[str]:
    """Return numeric values and non-sentence-initial capitalised values."""
    values: list[str] = []
    for index, word in enumerate(words):
        value = _norm(word)
        if _NUMBER.fullmatch(value):
            values.append(value.rstrip(".,"))
        elif (
            value[:1].isupper()
            and (index > 0 or not starts_sentence)
            and (index == 0 or not words[index - 1].endswith((".", "!", "?")))
        ):
            values.append(value)
    return values


def _same(old: str, new: str) -> bool:
    """Whether two word values are a spelling or inflectional variation."""
    if old.isdigit() or new.isdigit() or any(char.isdigit() for char in old + new):
        return old == new
    if new.startswith(old) or old.startswith(new):
        return True
    shared = 0
    while shared < min(len(old), len(new)) and old[shared] == new[shared]:
        shared += 1
    if shared >= 4 and shared >= 0.6 * min(len(old), len(new)):
        return True
    return (
        len(old) == len(new) and sorted(old) == sorted(new)
    ) or difflib.SequenceMatcher(None, old, new).ratio() >= 0.8


@dataclass(frozen=True)
class ValueSwap:
    """One replace operation's positional value pairs."""

    pairs: tuple[tuple[str, str], ...]


def swaps(old_text: str, new_text: str) -> list[ValueSwap]:
    """Return positional, non-equivalent value pairs for small replace operations."""
    old_words, new_words = old_text.split(), new_text.split()
    found: list[ValueSwap] = []
    for operation, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, old_words, new_words, autojunk=False
    ).get_opcodes():
        if operation != "replace" or old_end - old_start > 6 or new_end - new_start > 6:
            continue
        old_values = _values(
            old_words[old_start:old_end],
            old_start == 0 or old_words[old_start - 1].endswith((".", "!", "?")),
        )
        new_values = _values(
            new_words[new_start:new_end],
            new_start == 0 or new_words[new_start - 1].endswith((".", "!", "?")),
        )
        pairs: list[tuple[str, str]] = []
        for old_value, new_value in zip(old_values, new_values, strict=False):
            if (
                old_value[:1].isdigit() == new_value[:1].isdigit()
                and not _same(old_value, new_value)
                and old_value not in new_text
                and new_value not in old_text
            ):
                pairs.append((old_value, new_value))
        if pairs:
            found.append(ValueSwap(tuple(pairs)))
    return found

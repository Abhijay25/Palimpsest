"""Deterministic detection of values replaced in an edit."""

import difflib
import re

_TOKEN = re.compile(r"\d[\d.,]*|[A-ZÅÄÖ][\w'-]+(?:\s[A-ZÅÄÖ][\w'-]+)*")
_NUMBER = re.compile(r"\d[\d.,]*")


def _norm(value: str) -> str:
    """Remove presentation punctuation which is not part of a value."""
    value = value.strip("()[]{}\"'“”«»|=").rstrip(".,;:")
    return re.sub(r"['’]s$", "", value)


def _values(words: list[str]) -> set[str]:
    """Return numeric values and non-sentence-initial capitalised values."""
    values: set[str] = set()
    for index, word in enumerate(words):
        value = _norm(word)
        if _NUMBER.fullmatch(value):
            values.add(value.rstrip(".,"))
        elif (
            value[:1].isupper()
            and index > 0
            and not words[index - 1].endswith((".", "!", "?"))
        ):
            values.add(value)
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


def swaps(old_text: str, new_text: str) -> list[tuple[set[str], set[str]]]:
    """Return replaced, non-equivalent values grouped by changed text span."""
    old_words, new_words = old_text.split(), new_text.split()
    found: list[tuple[set[str], set[str]]] = []
    for operation, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, old_words, new_words, autojunk=False
    ).get_opcodes():
        if operation != "replace":
            continue
        old_context = old_words[max(0, old_start - 1) : old_end]
        new_context = new_words[max(0, new_start - 1) : new_end]
        old_prefix = old_words[max(0, old_start - 1) : old_start]
        new_prefix = new_words[max(0, new_start - 1) : new_start]
        old_values = _values(old_context) - _values(old_prefix)
        new_values = _values(new_context) - _values(new_prefix)
        gone = {
            value
            for value in old_values
            if not any(_same(value, replacement) for replacement in new_values)
            and value not in new_text
        }
        came = {
            value
            for value in new_values
            if not any(_same(value, replacement) for replacement in old_values)
            and value not in old_text
        }
        for numeric in (True, False):
            old_kind = {value for value in gone if value[:1].isdigit() == numeric}
            new_kind = {value for value in came if value[:1].isdigit() == numeric}
            if old_kind and new_kind:
                found.append((old_kind, new_kind))
    return found

"""Split an edit into independently judgeable changed units (paragraph alignment)."""

import difflib
import re
from typing import Final, Literal

from pydantic import BaseModel

from palimpsest.stage0 import strip_wikitext

TINY_UNIT_CHARS: Final = 40
_PARAGRAPH_BREAK_RE: Final = re.compile(r"\n[ \t]*\n")

UnitKind = Literal["changed", "inserted", "deleted"]


class EditUnit(BaseModel):
    index: int
    old_text: str
    new_text: str
    old_wikitext: str | None
    new_wikitext: str | None
    kind: UnitKind


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_BREAK_RE.split(text) if p.strip()]


def _normalise(paragraph: str) -> str:
    return " ".join(paragraph.split())


def _plain(paragraph: str | None, use_wikitext: bool) -> str:
    if paragraph is None:
        return ""
    return strip_wikitext(paragraph).strip() if use_wikitext else paragraph


def _make_unit(old: str | None, new: str | None, use_wikitext: bool) -> EditUnit:
    kind: UnitKind = (
        "changed"
        if old is not None and new is not None
        else ("inserted" if new is not None else "deleted")
    )
    return EditUnit(
        index=0,
        old_text=_plain(old, use_wikitext),
        new_text=_plain(new, use_wikitext),
        old_wikitext=old if use_wikitext else None,
        new_wikitext=new if use_wikitext else None,
        kind=kind,
    )


def _join(first: str | None, second: str | None) -> str | None:
    parts = [p for p in (first, second) if p]
    if first is None and second is None:
        return None
    return "\n\n".join(parts)


def _merge(first: EditUnit, second: EditUnit) -> EditUnit:
    old_text = _join(first.old_text, second.old_text) or ""
    new_text = _join(first.new_text, second.new_text) or ""
    return EditUnit(
        index=0,
        old_text=old_text,
        new_text=new_text,
        old_wikitext=_join(first.old_wikitext, second.old_wikitext),
        new_wikitext=_join(first.new_wikitext, second.new_wikitext),
        kind="changed" if old_text and new_text else first.kind,
    )


def _is_tiny(unit: EditUnit) -> bool:
    return (
        unit.kind != "changed"
        and len(unit.old_text) + len(unit.new_text) < TINY_UNIT_CHARS
    )


def _merge_tiny(units: list[EditUnit]) -> list[EditUnit]:
    merged = list(units)
    position = 0
    while position < len(merged) and len(merged) > 1:
        if not _is_tiny(merged[position]):
            position += 1
            continue
        if position > 0:
            merged[position - 1] = _merge(merged[position - 1], merged[position])
            del merged[position]
        else:
            merged[1] = _merge(merged[0], merged[1])
            del merged[0]
    return merged


def changed_chars(unit: EditUnit) -> int:
    """Characters in the unit that differ between old and new (word-level)."""
    old_words = unit.old_text.split()
    new_words = unit.new_text.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        total += sum(len(w) for w in old_words[i1:i2])
        total += sum(len(w) for w in new_words[j1:j2])
    return total


def split_edit(
    old_text: str,
    new_text: str,
    old_wikitext: str | None,
    new_wikitext: str | None,
) -> list[EditUnit]:
    use_wikitext = old_wikitext is not None and new_wikitext is not None
    # Wikitext on both sides or plain text on both: never mix the two forms.
    if old_wikitext is not None and new_wikitext is not None:
        old_paras = _paragraphs(old_wikitext)
        new_paras = _paragraphs(new_wikitext)
    else:
        old_paras = _paragraphs(old_text)
        new_paras = _paragraphs(new_text)
        old_wikitext = new_wikitext = None
    if len(old_paras) <= 1 and len(new_paras) <= 1:
        return [
            EditUnit(
                index=0,
                old_text=old_text,
                new_text=new_text,
                old_wikitext=old_wikitext,
                new_wikitext=new_wikitext,
                kind="changed",
            )
        ]
    prefix = 0
    limit = min(len(old_paras), len(new_paras))
    while prefix < limit and old_paras[prefix] == new_paras[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < limit - prefix
        and old_paras[len(old_paras) - 1 - suffix]
        == new_paras[len(new_paras) - 1 - suffix]
    ):
        suffix += 1
    old_mid = slice(prefix, len(old_paras) - suffix)
    new_mid = slice(prefix, len(new_paras) - suffix)
    old_keys = [_normalise(p) for p in old_paras[old_mid]]
    new_keys = [_normalise(p) for p in new_paras[new_mid]]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    units: list[EditUnit] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        olds = old_paras[old_mid][i1:i2]
        news = new_paras[new_mid][j1:j2]
        paired = min(len(olds), len(news))
        for k in range(paired):
            units.append(_make_unit(olds[k], news[k], use_wikitext))
        units.extend(_make_unit(None, n, use_wikitext) for n in news[paired:])
        units.extend(_make_unit(o, None, use_wikitext) for o in olds[paired:])
    units = _merge_tiny(units)
    return [u.model_copy(update={"index": i}) for i, u in enumerate(units)]

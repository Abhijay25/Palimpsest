from pathlib import Path

from pydantic import BaseModel

from palimpsest.value_swaps import swaps


class _Excerpt(BaseModel):
    title: str
    old: str
    new: str


def test_inflection_and_extension_are_not_value_swaps() -> None:
    assert swaps("It is Nummen.", "It is Nummella.") == []
    assert swaps("It is Söregi.", "It is Söregi-Vilén.") == []


def test_spelling_fix_and_possessive_are_not_value_swaps() -> None:
    assert swaps("It is Gavilan.", "It is Galivan.") == []
    assert swaps("It is James's book.", "It is James book.") == []


def test_sentence_initial_capitals_are_not_names() -> None:
    assert swaps("Alice wrote it.", "Beth wrote it.") == []


def test_bracketed_years_are_detected() -> None:
    assert [
        change.pairs
        for change in swaps("The event (1997) happened.", "The event (2009) happened.")
    ] == [(("1997", "2009"),)]


def test_number_and_name_are_not_paired() -> None:
    assert swaps("The date was 1997.", "The date was Alice.") == []


def test_large_real_list_replacement_is_not_a_value_swap() -> None:
    fixture = _Excerpt.model_validate_json(
        (Path(__file__).parent / "fixtures/big_1385647429_value_swap.json").read_text()
    )
    assert fixture.title == "Out-of-town shopping centres in the United Kingdom"
    assert swaps(fixture.old, fixture.new) == []


def test_values_are_paired_by_position_once_per_replace_operation() -> None:
    found = swaps(
        "The records Alpha Beta 1997.",
        "The records Gamma Delta 2009.",
    )
    assert [change.pairs for change in found] == [
        (("Alpha", "Gamma"), ("Beta", "Delta"), ("1997", "2009"))
    ]

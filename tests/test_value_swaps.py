from palimpsest.value_swaps import swaps


def test_inflection_and_extension_are_not_value_swaps() -> None:
    assert swaps("It is Nummen.", "It is Nummella.") == []
    assert swaps("It is Söregi.", "It is Söregi-Vilén.") == []


def test_spelling_fix_and_possessive_are_not_value_swaps() -> None:
    assert swaps("It is Gavilan.", "It is Galivan.") == []
    assert swaps("It is James's book.", "It is James book.") == []


def test_sentence_initial_capitals_are_not_names() -> None:
    assert swaps("Alice wrote it.", "Beth wrote it.") == []


def test_bracketed_years_are_detected() -> None:
    assert swaps("The event (1997) happened.", "The event (2009) happened.") == [
        ({"1997"}, {"2009"})
    ]


def test_number_and_name_are_not_paired() -> None:
    assert swaps("The date was 1997.", "The date was Alice.") == []

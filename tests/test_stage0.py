from palimpsest.stage0 import (
    extract_ref_urls,
    prefilter,
    refs_for_changed_sentences,
    strip_wikitext,
)


def test_typo_fix_is_clean() -> None:
    result = prefilter("He recieved the award.", "He received the award.", "en")
    assert result.clean
    assert result.reasons == []


def test_punctuation_markup_is_clean() -> None:
    result = prefilter(
        "He moved to [[Helsinki]] in May", "He moved to Helsinki, in May", "en"
    )
    assert result.clean


def test_identical_is_clean() -> None:
    assert prefilter("Same text.", "Same text.", "en").clean


def test_number_change_not_clean() -> None:
    result = prefilter("Growth was 3.2% last year.", "Growth was 5.2% last year.", "en")
    assert not result.clean
    assert result.reasons


def test_negation_not_clean() -> None:
    result = prefilter(
        "The senator voted for the bill.",
        "The senator did not vote for the bill.",
        "en",
    )
    assert not result.clean
    assert any("negation" in r for r in result.reasons)


def test_factive_verb_swap_not_clean() -> None:
    result = prefilter(
        "The minister stated the fund was used.",
        "The minister admitted the fund was used.",
        "en",
    )
    assert not result.clean
    assert any("factive" in r for r in result.reasons)


def test_motive_phrase_not_clean() -> None:
    result = prefilter(
        "He donated $1M.",
        "He donated $1M in order to distract from the investigation.",
        "en",
    )
    assert not result.clean


def test_ref_url_swap_not_clean() -> None:
    old = "Sales rose.<ref>{{cite web|url=https://a.example/x|title=A}}</ref>"
    new = "Sales rose.<ref>{{cite web|url=https://b.example/y|title=A}}</ref>"
    result = prefilter(old, new, "en")
    assert not result.clean
    assert any("ref" in r for r in result.reasons)


def test_ref_only_name_change_same_urls_is_clean() -> None:
    old = 'Sales rose.<ref name="a">https://a.example/x</ref>'
    new = 'Sales rose.<ref name="b">https://a.example/x</ref>'
    assert prefilter(old, new, "en").clean


def test_insertion_not_clean() -> None:
    result = prefilter("", "A new sentence.", "en")
    assert not result.clean


def test_deletion_not_clean() -> None:
    assert not prefilter("An old sentence.", "", "en").clean


def test_word_reorder_not_clean() -> None:
    assert not prefilter("Alice sued Bob.", "Bob sued Alice.", "en").clean


def test_fi_inflected_doubt_verb_not_clean() -> None:
    result = prefilter("Ministeri sanoi näin.", "Ministeri väitti näin.", "fi")
    assert not result.clean
    assert any("doubt" in r for r in result.reasons)


def test_fi_inflected_forms_match() -> None:
    for form in ("väitti", "väittää", "väitetysti"):
        result = prefilter("Hän sanoi sen.", f"Hän {form} sen.", "fi")
        assert not result.clean
        assert any("doubt" in r for r in result.reasons), form


def test_fi_prefix_does_not_overmatch_short_negation() -> None:
    result = prefilter("Hän ilmoitti sen.", "Hän ilmoitti sen!", "fi")
    assert result.clean


def test_template_change_not_clean() -> None:
    result = prefilter(
        "It is {{convert|5|km}} long.", "It is {{convert|9|km}} long.", "en"
    )
    assert not result.clean


def test_extract_ref_urls() -> None:
    text = (
        'A.<ref>{{cite web|url=https://a.example/x|title=T}}</ref> B.<ref name="n" />'
        "<ref>https://b.example/y accessed</ref> [https://body.example body]"
    )
    assert extract_ref_urls(text) == ["https://a.example/x", "https://b.example/y"]


def test_strip_wikitext_removes_refs_and_markup() -> None:
    assert (
        strip_wikitext("[[Helsinki|City]] is big.<ref>https://a.example</ref>").strip()
        == "City is big."
    )


def test_longer_typo_fix_is_clean() -> None:
    result = prefilter(
        "regular maintainence was performed",
        "regular maintenance was performed",
        "en",
    )
    assert result.clean


def test_different_word_same_length_not_clean() -> None:
    result = prefilter("the vote was won", "the vote was lost", "en")
    assert not result.clean


def test_refs_for_changed_sentences_uncited_addition() -> None:
    old = "Zvada signed in April.<ref>https://a.example/signed</ref>"
    new = old + " In November the fee was waived."
    assert refs_for_changed_sentences(old, new) == []


def test_refs_for_changed_sentences_added_with_own_ref() -> None:
    old = "Zvada signed in April.<ref>https://a.example/signed</ref>"
    new = old + " The fee was waived.<ref>https://b.example/waived</ref>"
    assert refs_for_changed_sentences(old, new) == ["https://b.example/waived"]


def test_refs_for_changed_sentences_modified_keeps_ref() -> None:
    old = "Zvada signed in April.<ref>https://a.example/signed</ref> Other."
    new = "Zvada reluctantly signed in April.<ref>https://a.example/signed</ref> Other."
    assert refs_for_changed_sentences(old, new) == ["https://a.example/signed"]


def test_refs_for_changed_sentences_inner_ref_and_dedup() -> None:
    old = "Alpha beta."
    new = "Alpha beta. He said<ref>https://a.example/x</ref> it twice.<ref>https://a.example/x</ref>"
    assert refs_for_changed_sentences(old, new) == ["https://a.example/x"]


def test_refs_for_changed_sentences_named_reuse() -> None:
    old = 'Old claim.<ref name="x">https://a.example/x</ref>'
    new = old + ' New claim.<ref name="x" /> Third.<ref name=y />'
    assert refs_for_changed_sentences(old, new) == ["https://a.example/x"]


def test_language_without_watch_list_still_prefiltered() -> None:
    result = prefilter(
        "Der Bürgermeister unterschrieb.", "Der Bürgermeister bekämpfte.", "de"
    )
    assert not result.clean
    assert "token change beyond single typo" in result.reasons
    assert not prefilter("Er hat 5 Autos.", "Er hat 6 Autos.", "de").clean
    assert prefilter("Er recieved Autos.", "Er received Autos.", "de").clean

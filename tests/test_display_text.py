from palimpsest import display_text


def test_plain_strips_refs_templates_links_and_quotes() -> None:
    wikitext = (
        "'''Jose Villa''' (born 1980) is an American [[Fine-art photography|fine art]] "
        'photographer.<ref name="a">{{Cite web |url=https://x.example/a |title=T}}</ref>'
        '<ref name=":7" /> He works in [[Texas]].{{citation needed|date=May 2025}}'
    )
    assert display_text.plain(wikitext) == (
        "Jose Villa (born 1980) is an American fine art photographer. He works in Texas."
    )


def test_plain_handles_nested_templates_and_external_links() -> None:
    assert display_text.plain(
        "A {{a|{{b|c}}}}b [https://x.example label] [https://y.example] c"
    ) == ("A b label c")


def test_sentence_with_returns_only_the_anchor_sentence() -> None:
    text = "First sentence here. He is a great American photographer. Last one."
    assert display_text.sentence_with(text, "a great American") == (
        "He is a great American photographer."
    )


def test_matching_sentence_finds_the_counterpart_or_none() -> None:
    old = "Intro. He is an American photographer. Other text entirely."
    assert display_text.matching_sentence(
        old, "He is a great American photographer."
    ) == ("He is an American photographer.")
    assert (
        display_text.matching_sentence(old, "Completely unrelated words xyz.") is None
    )


def test_shorten_keeps_focus_visible_with_ellipses() -> None:
    text = "word " * 100 + "FOCUS " + "word " * 100
    short = display_text.shorten(text, 60, "FOCUS")
    assert "FOCUS" in short and short.startswith("…") and short.endswith("…")
    assert len(short) <= 62

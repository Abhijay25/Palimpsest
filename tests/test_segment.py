import time

from palimpsest.segment import split_edit

PARA = "This is a reasonably long paragraph about topic number {n} with detail."


def _article(n: int, overrides: dict[int, str] | None = None) -> str:
    overrides = overrides or {}
    return "\n\n".join(overrides.get(i, PARA.format(n=i)) for i in range(n))


def test_single_paragraph_is_passthrough() -> None:
    units = split_edit("a b", "a c", None, None)
    assert len(units) == 1
    assert (units[0].old_text, units[0].new_text) == ("a b", "a c")
    assert units[0].kind == "changed"
    assert units[0].index == 0


def test_one_changed_paragraph() -> None:
    old = _article(5)
    new = _article(5, {2: "The mayor shamelessly pushed through the disastrous bill."})
    units = split_edit(old, new, None, None)
    assert len(units) == 1
    assert units[0].kind == "changed"
    assert units[0].old_text == PARA.format(n=2)


def test_inserted_and_deleted_units() -> None:
    base = [PARA.format(n=i) for i in range(4)]
    long_new = "A brand new paragraph that is definitely longer than forty chars."
    inserted = split_edit(
        "\n\n".join(base), "\n\n".join([*base[:2], long_new, *base[2:]]), None, None
    )
    assert [u.kind for u in inserted] == ["inserted"]
    deleted = split_edit(
        "\n\n".join(base), "\n\n".join(base[:1] + base[2:]), None, None
    )
    assert [u.kind for u in deleted] == ["deleted"]
    assert deleted[0].old_text == base[1]


def test_replace_region_pairs_and_leftovers() -> None:
    long_a = "Alpha paragraph that is long enough to avoid any tiny merging rule."
    long_b = "Bravo paragraph that is long enough to avoid any tiny merging rule."
    long_c = "Charlie paragraph that is long enough to avoid tiny merging rules."
    old = f"keep one here\n\n{PARA.format(n=1)}\n\n{PARA.format(n=2)}\n\nkeep two here"
    new = f"keep one here\n\n{long_a}\n\n{long_b}\n\n{long_c}\n\nkeep two here"
    units = split_edit(old, new, None, None)
    assert [u.kind for u in units] == ["changed", "changed", "inserted"]


def test_tiny_unit_merges_into_neighbour() -> None:
    old = f"{PARA.format(n=0)}\n\n{PARA.format(n=1)}\n\ntail para unchanged here"
    new = f"{PARA.format(n=0)}\n\nChanged paragraph one is now quite different text.\n\nx\n\ntail para unchanged here"
    units = split_edit(old, new, None, None)
    assert len(units) == 1
    assert units[0].new_text.endswith("\n\nx")


def test_wikitext_units_derive_plain_text() -> None:
    old_wiki = (
        "Intro line stays the same here.\n\nThe '''mayor''' signed the bill into law."
    )
    new_wiki = "Intro line stays the same here.\n\nThe '''mayor''' shamelessly signed the bill into law."
    units = split_edit("x", "y", old_wiki, new_wiki)
    assert len(units) == 1
    assert units[0].new_text == "The mayor shamelessly signed the bill into law."
    assert units[0].new_wikitext is not None and "'''" in units[0].new_wikitext


def test_equal_multi_paragraph_yields_no_units() -> None:
    text = _article(3)
    assert split_edit(text, text, None, None) == []


def test_large_article_splits_fast() -> None:
    n = 3000
    old = _article(n)
    new = _article(
        n,
        {
            100: "Changed paragraph one with plenty of extra words in it for size.",
            1500: "Changed paragraph two with plenty of extra words in it for size.",
            2900: "Changed paragraph three with plenty of extra words in it for size.",
        },
    )
    assert len(old) > 200_000
    start = time.perf_counter()
    units = split_edit(old, new, None, None)
    elapsed = time.perf_counter() - start
    assert len(units) == 3
    assert elapsed < 0.05

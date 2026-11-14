"""Real browser checks for DOM Range to verified UTF-16 offsets.

Run inside the pinned Playwright browser image from the repository root:
python tests/js/selection_ranges_browser.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "infra/wiki/extensions/PalimpsestBlame/resources/helpers.js"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(
            """
            <main id="fixture">
              <p id="cross"><span id="alpha" data-pb-start="0" data-pb-end="5">alpha</span><em> gap </em><span id="beta" data-pb-start="10" data-pb-end="14">beta</span></p>
              <p id="emoji"><span id="face" data-pb-start="20" data-pb-end="23">😀X</span></p>
              <p id="markup"><span id="formatted" data-pb-start="30" data-pb-end="32"><b>a</b><i>b</i></span></p>
              <p id="offset-gap"><span id="first" data-pb-start="40" data-pb-end="41">a</span><b></b><span id="second" data-pb-start="50" data-pb-end="51">b</span></p>
              <p id="outside">unmapped outside text</p>
              <p id="many"></p>
            </main>
            """
        )
        page.add_script_tag(path=str(HELPER))
        page.evaluate(
            """() => {
                const many = document.querySelector('#many');
                for (let i = 0; i < 65; i++) {
                    const span = document.createElement('span');
                    span.dataset.pbStart = String(100 + i * 3);
                    span.dataset.pbEnd = String(101 + i * 3);
                    span.textContent = 'x';
                    many.append(span, document.createTextNode(' '));
                }
            }"""
        )
        result = page.evaluate(
            """() => {
                const helper = window.PalimpsestBlameHelpers;
                const text = id => document.querySelector('#' + id).firstChild;
                const inspect = (startNode, startOffset, endNode, endOffset, reverse) => {
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    if (reverse && selection.setBaseAndExtent) {
                        selection.setBaseAndExtent(endNode, endOffset, startNode, startOffset);
                    } else {
                        const range = document.createRange();
                        range.setStart(startNode, startOffset);
                        range.setEnd(endNode, endOffset);
                        selection.addRange(range);
                    }
                    const output = helper.selectionRanges(selection);
                    selection.removeAllRanges();
                    return output;
                };
                const cross = inspect(text('alpha'), 2, text('beta'), 2, false);
                const emoji = inspect(text('face'), 0, text('face'), 2, true);
                const formatted = inspect(document.querySelector('#formatted').firstChild.firstChild, 0, document.querySelector('#formatted').lastChild.lastChild, 1, false);
                const offsetGap = inspect(text('first'), 0, text('second'), 1, false);
                const outside = inspect(text('outside'), 0, text('outside'), 8, false);
                const collapsed = inspect(text('alpha'), 2, text('alpha'), 2, false);
                const selection = window.getSelection();
                selection.removeAllRanges();
                const all = document.createRange();
                all.selectNodeContents(document.querySelector('#many'));
                selection.addRange(all);
                const fragments = helper.selectionRanges(selection);
                selection.removeAllRanges();
                return { cross, emoji, formatted, offsetGap, outside, collapsed, fragments };
            }"""
        )
        assert result["cross"]["exactText"] == "pha gap be"
        assert result["cross"]["ranges"] == [{"start": 2, "end": 5}, {"start": 10, "end": 12}]
        assert any("no verified source offset" in gap["reason"] for gap in result["cross"]["unmapped"])
        assert result["emoji"]["ranges"] == [{"start": 20, "end": 22}], result["emoji"]
        assert result["formatted"]["ranges"] == [{"start": 30, "end": 32}], result["formatted"]
        assert not result["offsetGap"]["unmapped"], result["offsetGap"]
        assert result["offsetGap"]["ranges"] == [{"start": 40, "end": 41}, {"start": 50, "end": 51}]
        assert result["outside"]["ranges"] == [] and result["outside"]["unmapped"]
        assert result["collapsed"]["ranges"] == []
        assert len(result["fragments"]["ranges"]) == 65, len(result["fragments"]["ranges"])
        browser.close()
    print("DOM selection mapping cases passed: cross-span gaps, reverse UTF-16, inline formatting, markup-only source gap, unmapped, collapsed, and >64 ranges")


if __name__ == "__main__":
    main()

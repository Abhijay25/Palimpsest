"""Pinned Playwright acceptance for the local Blame action on all three wikis.

Run only inside the existing Playwright 1.65.1 browser image. The operator
supplies explicit browser-reachable origins; this script never guesses Docker
Desktop host routing or manages a runtime.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, quote, urlparse

from mediawiki_api import WikiApi

from playwright.sync_api import Page, expect, sync_playwright


LANGS = ("fi", "sv", "en")
BASE_ORIGIN_ENV = {language: f"PALIMPSEST_BLAME_BROWSER_ORIGIN_{language.upper()}" for language in LANGS}
FIXTURE_IDS = (
    "cross_contributor_deletion", "chained_replacements", "repeated_move_revert",
    "unicode_utf16_selection", "date_boundaries", "large_unique_anchor_history",
)
FIXTURE_DIR = Path(__file__).parent / "fixtures"
INSPECT_BUTTON_NAME = re.compile(r"inspect (?:selected (?:article )?text|selection)|analyze selection", re.I)


def load_fixture(fixture_id: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))


def article_url(origin: str, title: str) -> str:
    return f"{origin.rstrip('/')}/index.php?title={quote(title, safe=':') }"


def find_blame_link(page: Page):
    candidates = page.get_by_role("link", name=re.compile(r"\bBlame\b", re.I))
    expect(candidates.first).to_be_visible()
    return candidates.first


def tab_to_element(page: Page, target, description: str, max_tabs: int = 256) -> None:
    for _ in range(max_tabs):
        if target.evaluate("element => document.activeElement === element"):
            return
        page.keyboard.press("Tab")
    raise AssertionError(f"keyboard tab order never reached {description}")


def enter_blame_with_keyboard(page: Page) -> None:
    content = page.locator("#mw-content-text")
    expect(content).to_be_visible()
    expect(content).to_contain_text(load_fixture("cross_contributor_deletion")["revisions"][-1]["text"])
    link = find_blame_link(page)
    tab_to_element(page, link, "the visible Blame action link")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"[?&]action=blame(?:&|$)"))
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    wait_for_article_selection_ready(
        page,
        load_fixture("cross_contributor_deletion")["revisions"][-1]["text"],
    )


def verify_keyboard_phrase_activation(page: Page, phrase: str, key: str) -> None:
    wait_for_article_selection_ready(page, phrase)
    target = page.locator("#mw-content-text [data-pb-start]").filter(
        has_text=re.compile(rf"^{re.escape(phrase)}$")
    ).first
    expect(target).to_be_visible()
    if target.inner_text().strip() != phrase:
        raise AssertionError(f"keyboard target text differs from exact attributed phrase {phrase!r}")
    tab_to_element(page, target, f"the attributed phrase {phrase!r}")
    captured = target.evaluate(
        """(element) => {
          const block = element.closest('p,li,td,blockquote,pre,h1,h2,h3,h4,h5,h6,dt,dd');
          if (!block) return false;
          window.__pbAcceptanceKeyboardTarget = element;
          window.__pbAcceptanceSelection = {
            text: element.innerText || element.textContent || '',
            startBlock: block,
            endBlock: block
          };
          return true;
        }"""
    )
    if not captured:
        raise AssertionError(f"attributed phrase {phrase!r} has no enclosing article end block")
    page.keyboard.press(key)
    panel = page.locator("#palimpsest-blame")
    breakdown = panel.locator(".pb-breakdown")
    expect(breakdown).to_be_visible()
    expect(breakdown).to_contain_text(phrase)
    verify_inline_panel(page, phrase)

    page.keyboard.press("Escape")
    expect(breakdown).to_be_hidden()
    expect(target).to_be_focused()


def wait_for_article_selection_ready(page: Page, quote: str) -> None:
    page.wait_for_function(
        """({quote}) => {
          const root = document.querySelector('#mw-content-text');
          const panel = document.querySelector('#palimpsest-blame');
          if (!root || !panel || panel.dataset.state === 'loading') return false;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
              return node.parentElement?.closest('#palimpsest-blame')
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            }
          });
          let articleText = '';
          while (walker.nextNode()) articleText += walker.currentNode.nodeValue || '';
          return articleText.includes(quote) && articleText.trim() !== 'Loading verified revision history…';
        }""",
        arg={"quote": quote},
        timeout=15000,
    )


def select_text(page: Page, quote: str, occurrence: int = 0) -> None:
    wait_for_article_selection_ready(page, quote)
    selected = page.evaluate(
        """({quote, occurrence}) => {
          const root = document.querySelector('#mw-content-text');
          if (!root) return null;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
              return node.parentElement?.closest('#palimpsest-blame')
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            }
          });
          const nodes = []; let full = '';
          while (walker.nextNode()) { nodes.push({node: walker.currentNode, start: full.length}); full += walker.currentNode.nodeValue || ''; }
          let begin = -1, cursor = 0;
          for (let index = 0; index <= occurrence; index++) {
            begin = full.indexOf(quote, cursor);
            if (begin < 0) return null;
            cursor = begin + quote.length;
          }
          const finish = begin + quote.length;
          const locate = (offset, isEnd) => {
            for (const item of nodes) {
              const length = item.node.nodeValue.length;
              if (offset >= item.start && (offset < item.start + length || (isEnd && offset === item.start + length))) {
                return {node: item.node, offset: offset - item.start};
              }
            }
            return null;
          };
          const a = locate(begin, false), b = locate(finish, true);
          if (!a || !b) return null;
          const range = document.createRange(); range.setStart(a.node, a.offset); range.setEnd(b.node, b.offset);
          const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
          const rangeSnapshot = selection.getRangeAt(0).cloneRange();
          const nearestBlock = (node) => {
            const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
            return element?.closest('p,li,td,blockquote,pre,h1,h2,h3,h4,h5,h6,dt,dd') || null;
          };
          const startBlock = nearestBlock(rangeSnapshot.startContainer);
          const endBlock = nearestBlock(rangeSnapshot.endContainer);
          window.__pbAcceptanceSelection = {
            text: selection.toString(),
            startBlock,
            endBlock
          };
          return {text: selection.toString(), start: begin, end: finish};
        }""",
        {"quote": quote, "occurrence": occurrence},
    )
    if not selected or selected["text"] != quote:
        raise AssertionError(f"could not select exact unique text {quote!r} from the rendered article")


def inspect_selected_text(page: Page, mobile: bool) -> None:
    button = page.get_by_role("button", name=INSPECT_BUTTON_NAME)
    expect(button).to_be_visible()
    if mobile:
        button.tap()
        # Mobile browsers may drop the native Range when the inspect button is
        # tapped. The component must retain the user quote it captured earlier.
        page.evaluate("window.getSelection()?.removeAllRanges()")
    else:
        # A scripted Range does not synthesize the producer's mouseup/Inspect
        # gesture. Exercise the same explicit action a reader must use.
        button.click()


def assert_no_partial_selection_analysis(page: Page, quote: str, warning: re.Pattern) -> None:
    requests = []

    def capture_analyze(request) -> None:
        params = parse_qs(urlparse(request.url).query)
        if request.post_data:
            from urllib.parse import parse_qs as parse_form
            for key, values in parse_form(request.post_data).items():
                params.setdefault(key, values)
        if params.get("action") == ["palimpsestblame"] and params.get("op") == ["analyze"]:
            requests.append(params)

    page.on("request", capture_analyze)
    select_text(page, quote)
    if page.evaluate("window.getSelection()?.toString() || ''") != quote:
        raise AssertionError("browser did not retain the exact source quote before inspection")
    page.get_by_role("button", name="Inspect selected article text").click()
    page.wait_for_timeout(150)
    if requests:
        raise AssertionError(f"selection with unmapped or excessive fragments triggered partial attribution: {requests}")
    if page.evaluate("window.getSelection()?.toString() || ''") != quote:
        raise AssertionError("Inspect did not retain the complete native selection quote")
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text(warning)
    if panel.locator(".pb-breakdown").count():
        raise AssertionError("selection with incomplete source mapping opened a partial timeline")


def verify_inline_panel(page: Page, quote: str, expected_end_block_text: str | None = None) -> None:
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text(quote)
    geometry = page.evaluate(
        """({quote, expectedEndBlockText}) => {
          const panel = document.querySelector('#palimpsest-blame');
          const root = document.querySelector('#mw-content-text');
          const selected = window.__pbAcceptanceSelection;
          const startBlock = selected?.startBlock;
          const endBlock = selected?.endBlock;
          if (!panel || !root || !selected || !startBlock || !endBlock) return null;
          if (!startBlock.isConnected || !endBlock.isConnected || !root.contains(startBlock) || !root.contains(endBlock) || !root.contains(panel)) return null;
          if (selected.text !== quote) return null;
          const endText = endBlock.innerText || endBlock.textContent || '';
          const sr = endBlock.getBoundingClientRect(), pr = panel.getBoundingClientRect();
          return {
            endText,
            matchesExpectedEndBlock: !expectedEndBlockText || endText.includes(expectedEndBlockText),
            spansBlocks: startBlock !== endBlock,
            panelTop: pr.top,
            endBlockBottom: sr.bottom,
            belowEndBlock: pr.top >= sr.bottom - 2
          };
        }""",
        {"quote": quote, "expectedEndBlockText": expected_end_block_text},
    )
    if not geometry:
        raise AssertionError("selected range's end block was not retained as a connected article node")
    if expected_end_block_text and (not geometry["spansBlocks"] or not geometry["matchesExpectedEndBlock"]):
        raise AssertionError(f"cross-paragraph range did not retain the expected selected end block {expected_end_block_text!r}: {geometry}")
    if not geometry["belowEndBlock"]:
        raise AssertionError(f"inline breakdown is not rendered after the selected end block; producer may be anchoring to the first paragraph: {geometry}")


def verify_article_snapshot(page: Page, expected_visible_text: str, revision_id: int) -> None:
    content = page.locator("#mw-content-text")
    expect(content).to_be_visible()
    expect(content).to_contain_text(expected_visible_text)
    rendered_revision = page.evaluate("window.mw?.config?.get('wgRevisionId')")
    if int(rendered_revision or -1) != int(revision_id):
        raise AssertionError(f"rendered article revision {rendered_revision!r} differs from expected local revision {revision_id}")


def verify_mobile_layout(page: Page) -> None:
    metrics = page.evaluate(
        """() => ({
          innerWidth: window.innerWidth,
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth
        })"""
    )
    if not 360 <= metrics["clientWidth"] <= 430 or abs(metrics["innerWidth"] - metrics["clientWidth"]) > 2:
        raise AssertionError(f"mobile page is scaled to a desktop layout viewport: {metrics}")
    if metrics["scrollWidth"] > metrics["clientWidth"] + 2:
        raise AssertionError(f"mobile Blame view has horizontal overflow: {metrics}")


def exercise_selection(page: Page, fixture_id: str, mobile: bool, screenshot: Path | None) -> None:
    doc = load_fixture(fixture_id)
    expected = doc["expected"]
    quote = expected["selection"]["text"]
    select_text(page, quote, max(0, int(expected["selection"].get("occurrence", 1)) - 1))
    inspect_selected_text(page, mobile)
    verify_inline_panel(page, quote)
    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)


def open_selected_timeline(page: Page, quote: str, expected_article_text: str) -> None:
    article = page.locator("#mw-content-text")
    panel = page.locator("#palimpsest-blame")
    expect(article).to_be_visible()
    expect(article).to_contain_text(expected_article_text)
    expect(panel).to_be_visible()
    # The shell can appear while it still shows "Loading verified revision
    # history…"; wait for its ready state before mapping the selected quote.
    expect(panel).to_have_attribute("data-state", "ready")
    expect(article.locator("[data-pb-start]").first).to_be_visible()
    select_text(page, quote)
    inspect_selected_text(page, mobile=False)
    expect(panel.locator(".pb-breakdown")).to_be_visible()
    expect(panel).to_contain_text(quote)


def verify_replacement_timeline(page: Page) -> None:
    doc = load_fixture("chained_replacements")
    quote = doc["expected"]["selection"]["text"]
    article_text = doc["revisions"][-1]["text"]
    open_selected_timeline(page, quote, article_text)
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text("quick")
    expect(panel).to_contain_text("slow")
    expect(panel).to_contain_text("fast")
    expect(panel).to_contain_text("old")
    compare = panel.get_by_role("button", name=re.compile("compare with previous revision", re.I))
    if compare.count() == 0:
        compare = panel.get_by_role("link", name=re.compile("compare with previous revision", re.I))
    expect(compare.first).to_be_visible()
    with page.expect_navigation(wait_until="domcontentloaded"):
        compare.first.click()
    if "action=blame" in page.url or not re.search(r"(?:[?&](?:diff|oldid)=|Special:Diff)", page.url):
        raise AssertionError(f"revision comparison link did not open the core MediaWiki diff: {page.url}")
    page.go_back(wait_until="domcontentloaded")
    open_selected_timeline(page, quote, article_text)

    changes = panel.get_by_role("link", name=re.compile("view editor.?s changes", re.I))
    expect(changes.first).to_be_visible()
    with page.expect_navigation(wait_until="domcontentloaded"):
        changes.first.click()
    special_page = page.evaluate("window.mw?.config?.get('wgCanonicalSpecialPageName')")
    if "action=blame" in page.url or special_page != "Contributions":
        raise AssertionError(f"editor history link did not open the core Contributions page: {page.url} ({special_page!r})")
    page.go_back(wait_until="domcontentloaded")
    open_selected_timeline(page, quote, article_text)

    open_revision = panel.get_by_role("link", name="Open this revision")
    expect(open_revision.first).to_be_visible()
    with page.expect_navigation(wait_until="domcontentloaded"):
        open_revision.first.click()
    if "action=blame" in page.url or not re.search(r"[?&]oldid=\d+", page.url):
        raise AssertionError(f"Open this revision did not open a core MediaWiki read view: {page.url}")
    revision_query = parse_qs(urlparse(page.url).query)
    if str(page.evaluate("window.mw?.config?.get('wgRevisionId')")) != revision_query["oldid"][0]:
        raise AssertionError("Open this revision loaded content at a different local revision ID")
    page.go_back(wait_until="domcontentloaded")


def date_text_tomorrow_utc() -> str:
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return tomorrow.strftime("%-d %B %Y")


def verify_date_navigation(page: Page, expected_latest_text: str, latest_revision_id: int) -> None:
    panel = page.locator("#palimpsest-blame")
    date_input = panel.get_by_role("textbox", name=re.compile("date", re.I))
    expect(date_input).to_be_visible()
    tomorrow_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    tomorrow = tomorrow_date.strftime("%-d %B %Y")
    expected_before_bound = tomorrow_date.isoformat() + "T00:00:00Z"
    date_input.fill(f"Latest version before {tomorrow}")
    panel.get_by_role("button", name="Interpret date query").click()
    preview = panel.locator(".pb-date-preview")
    expect(preview).to_contain_text(re.compile(r"strictly before this UTC day begins", re.I))
    expect(preview).to_contain_text(expected_before_bound)
    panel.get_by_role("button", name="Apply these bounds").click()
    expect(panel).to_contain_text("UTC")
    version_results = panel.locator(".pb-version-results")
    before_result = version_results.get_by_role("button", name=re.compile(r"revision " + str(latest_revision_id) + r"\b"))
    expect(before_result).to_be_visible()
    before_result.click()
    verify_article_snapshot(page, expected_latest_text, latest_revision_id)

    date_input.fill("As of 15 March 2026")
    panel.get_by_role("button", name="Interpret date query").click()
    expect(panel.locator(".pb-date-preview")).to_contain_text("2026-03-15T23:59:59Z")
    panel.get_by_role("button", name="Apply these bounds").click()
    expect(panel).to_contain_text(re.compile("No revision matches these bounds", re.I))
    if version_results.locator(".pb-version").count():
        raise AssertionError("as-of before the earliest date offered a later version")

    date_input.fill(f"Between 1 January and {tomorrow}")
    panel.get_by_role("button", name="Interpret date query").click()
    expect(panel.locator(".pb-date-preview")).to_contain_text("inclusive UTC date range")
    panel.get_by_role("button", name="Apply these bounds").click()
    range_result = version_results.get_by_role("button", name=re.compile(str(latest_revision_id)))
    expect(range_result.first).to_be_visible()
    range_result.first.click()
    verify_article_snapshot(page, expected_latest_text, latest_revision_id)

    invalid_inputs = (
        ("As of 31 February 2026", re.compile("real calendar date", re.I)),
        ("Between 31 March and 1 February 2026", re.compile("start date must not be after the end date", re.I)),
    )
    for value, expected_error in invalid_inputs:
        date_input.fill(value)
        panel.get_by_role("button", name="Interpret date query").click()
        expect(panel.locator(".pb-date-preview")).to_contain_text(expected_error)


def verify_recovery(page: Page, expected_latest_text: str, expected_latest_revision_id: int) -> None:
    panel = page.locator("#palimpsest-blame")
    latest = panel.get_by_role("button", name=re.compile("return to latest|latest version", re.I))
    if latest.count() == 0:
        latest = panel.get_by_role("link", name=re.compile("return to latest|latest version", re.I))
    expect(latest.first).to_be_visible()
    latest.first.click()
    verify_article_snapshot(page, expected_latest_text, expected_latest_revision_id)


def verify_rendered_selection_cases(page: Page, origin: str, language_state: dict) -> None:
    browser_pages = language_state["browser_pages"]

    mapped = browser_pages["rendered_mapped_selection"]
    page.goto(article_url(origin, mapped["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    mapped_fixture = load_fixture("rendered_mapped_selection")
    verify_article_snapshot(page, mapped_fixture["visible_text"], mapped["revision_id"])
    select_text(page, mapped_fixture["selection_text"])
    inspect_selected_text(page, mobile=False)
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text(mapped_fixture["selection_text"])
    verify_inline_panel(page, mapped_fixture["selection_text"])
    if re.search(r"unmapped|unavailable|partial coverage", panel.inner_text(), re.I):
        raise AssertionError("formatting-only source markup gaps were misreported as unmapped visible words")
    # This real wiki link is relative to MediaWiki's /index.php/ base path.
    # It catches broken path-relative links after action=blame is added.
    ordinary_link = page.get_by_role("link", name=mapped_fixture["link_label"])
    expect(ordinary_link).to_be_visible()
    citation = page.locator('a[href*="#cite_note-"]').first
    expect(citation).to_be_visible()
    citation.click()
    expect(page).to_have_url(re.compile(r"#cite_note-"))
    expect(page.locator("#mw-content-text")).to_contain_text(mapped_fixture["citation_text"])
    ordinary_link.click()
    target = browser_pages["ordinary_link_target"]
    page_name = page.evaluate("window.mw?.config?.get('wgPageName')")
    if page_name != target["title"].replace(" ", "_"):
        raise AssertionError(f"ordinary article link opened {page_name!r}; expected canonical page {target['title']!r}")
    verify_article_snapshot(page, mapped_fixture["link_target_text"], target["revision_id"])
    if "action=blame" in page.url:
        raise AssertionError("ordinary article link was intercepted by the Blame selection UI")

    generated = browser_pages["generated_unmapped_selection"]
    generated_fixture = load_fixture("generated_unmapped_selection")
    page.goto(article_url(origin, generated["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    verify_article_snapshot(page, "The mapped prefix UNMAPPED_SENTINEL mapped suffix.", generated["revision_id"])
    generated_selection_quote = generated_fixture["selection_text_template"]
    assert_no_partial_selection_analysis(
        page, generated_selection_quote,
        re.compile(r"unmapped|no verified source|no partial analysis|cannot be mapped", re.I),
    )
    annotated = page.evaluate(
        """(sentinel) => {
          const root = document.querySelector('#mw-content-text');
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
              return node.parentElement?.closest('#palimpsest-blame')
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            }
          });
          while (walker.nextNode()) {
            if (!walker.currentNode.nodeValue.includes(sentinel)) continue;
            let element = walker.currentNode.parentElement;
            while (element && element !== root) {
              if (element.hasAttribute('data-pb-start') || element.hasAttribute('data-pb-revision') || element.classList.contains('pb-attributed')) return true;
              element = element.parentElement;
            }
            return false;
          }
          return null;
        }""",
        generated_fixture["generated_text"],
    )
    if annotated is not False:
        raise AssertionError("template-generated text received an authoritative source attribution marker")

    fragmented = browser_pages["fragmented_selection"]
    fragment_fixture = load_fixture("fragmented_selection")
    full_quote = " ".join(fragment_fixture["tokens"])
    page.goto(article_url(origin, fragmented["title"]) + "&action=blame", wait_until="domcontentloaded")
    verify_article_snapshot(page, full_quote, fragmented["revision_id"])
    if len(fragment_fixture["tokens"]) <= 64:
        raise AssertionError("fragmented selection fixture no longer exceeds the known 64-fragment regression threshold")
    assert_no_partial_selection_analysis(page, full_quote, re.compile(r"more than 64 separate verified source ranges.*no partial analysis", re.I))

    paragraph = browser_pages["paragraph_boundary_selection"]
    paragraph_fixture = load_fixture("paragraph_boundary_selection")
    page.goto(article_url(origin, paragraph["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#mw-content-text")).to_be_visible()
    if int(page.evaluate("window.mw?.config?.get('wgRevisionId')") or -1) != int(paragraph["revision_id"]):
        raise AssertionError("paragraph-boundary fixture rendered a different local revision")
    select_text(page, paragraph_fixture["selection_text"])
    inspect_selected_text(page, mobile=False)
    expect(page.locator("#palimpsest-blame")).to_contain_text(paragraph_fixture["selection_text"])
    verify_inline_panel(page, paragraph_fixture["selection_text"], expected_end_block_text="Second begins.")


def verify_mouse_partial_selection(page: Page, origin: str, cross: dict) -> None:
    page.goto(article_url(origin, cross["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    expected_article_text = load_fixture("cross_contributor_deletion")["revisions"][-1]["text"]
    wait_for_article_selection_ready(page, expected_article_text)
    coordinates = page.evaluate(
        """() => {
          const root = document.querySelector('#mw-content-text');
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
              return node.parentElement?.closest('#palimpsest-blame')
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            }
          });
          const nodes = []; let full = '';
          while (walker.nextNode()) {
            nodes.push({node: walker.currentNode, start: full.length});
            full += walker.currentNode.nodeValue || '';
          }
          const at = full.indexOf('green');
          if (at < 0) return null;
          const locate = (offset, isEnd) => {
            for (const item of nodes) {
              const length = item.node.nodeValue.length;
              if (offset >= item.start && (offset < item.start + length || (isEnd && offset === item.start + length))) {
                return {node: item.node, offset: offset - item.start};
              }
            }
            return null;
          };
          const start = locate(at + 1, false), end = locate(at + 4, true);
          if (!start || !end) return null;
          const range = document.createRange(); range.setStart(start.node, start.offset); range.setEnd(end.node, end.offset);
          const rects = [...range.getClientRects()].filter(rect => rect.width > 0 && rect.height > 0);
          if (!rects.length) return null;
          const first = rects[0], last = rects[rects.length - 1];
          if (Math.abs(first.top - last.top) > 1) return null;
          return {startX: first.left + 0.25, endX: last.right - 0.25, y: first.top + first.height / 2};
        }"""
    )
    if not coordinates or coordinates["endX"] <= coordinates["startX"]:
        raise AssertionError("could not place a mouse drag on a partial word range")
    page.mouse.move(coordinates["startX"], coordinates["y"])
    page.mouse.down()
    page.mouse.move(coordinates["endX"], coordinates["y"], steps=5)
    page.mouse.up()
    selected = page.evaluate("window.getSelection()?.toString() || ''")
    if selected != "ree":
        raise AssertionError(f"mouse drag selected {selected!r}; expected the exact partial word 'ree'")

    requested_ranges = []

    def capture_ranges(request) -> None:
        params = parse_qs(urlparse(request.url).query)
        if request.post_data:
            from urllib.parse import parse_qs as parse_form
            for key, values in parse_form(request.post_data).items():
                params.setdefault(key, values)
        if params.get("action") != ["palimpsestblame"]:
            return
        for value in params.get("ranges", []):
            try:
                requested_ranges.extend(json.loads(value))
            except (TypeError, json.JSONDecodeError):
                pass

    page.on("request", capture_ranges)
    inspect = page.get_by_role("button", name=INSPECT_BUTTON_NAME)
    expect(inspect).to_be_visible()
    inspect.click()
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text("ree")
    page.evaluate("window.getSelection()?.removeAllRanges()")
    expect(panel).to_contain_text("ree")
    if not any(item == {"start": 13, "end": 16} for item in requested_ranges):
        raise AssertionError(f"partial-word analysis did not send exact source offsets 13..16: {requested_ranges}")


def verify_concurrent_snapshot(page: Page, origin: str, language: str, auth: dict, run_id: str) -> int:
    title = f"PalimpsestBlameSynthetic/{run_id}/browser_concurrency_{language}"
    old_text = f"Reader sees the green marker before concurrent edit {run_id}."
    editor = WikiApi(origin.rstrip("/") + "/api.php")
    editor.login(auth["username"], auth["password"])
    old_id = editor.edit(title, old_text, f"[synthetic Blame concurrency baseline {run_id}] {language}")
    page.goto(article_url(origin, title) + "&action=blame", wait_until="domcontentloaded")
    verify_article_snapshot(page, old_text, old_id)
    wait_for_article_selection_ready(page, old_text)
    requested_revisions = []

    def capture_api_request(request) -> None:
        query = parse_qs(urlparse(request.url).query)
        if request.post_data:
            from urllib.parse import parse_qs as parse_form
            query.update(parse_form(request.post_data))
        if query.get("action") == ["palimpsestblame"]:
            requested_revisions.extend(query.get("revision", []))

    page.on("request", capture_api_request)
    new_text = old_text.replace("green", "black", 1) + f" concurrency{run_id}"
    new_id = editor.edit(title, new_text, f"[synthetic Blame concurrency update {run_id}] {language}")

    quote = "green marker"
    select_text(page, quote)
    inspect_selected_text(page, mobile=False)
    verify_inline_panel(page, quote)
    expect(page.locator("#mw-content-text")).to_contain_text("green")
    if "black" in page.locator("#mw-content-text").inner_text():
        raise AssertionError("article DOM silently changed to a newer revision while the reader was inspecting old content")
    if str(old_id) not in page.locator("#palimpsest-blame").inner_text():
        raise AssertionError("selection details do not identify the revision shown by the old article DOM")
    if str(old_id) not in requested_revisions:
        raise AssertionError(f"selection analysis request was not pinned to displayed revision {old_id}: {requested_revisions}")

    latest = page.locator("#palimpsest-blame").get_by_role("button", name=re.compile("return to latest|latest version", re.I))
    if latest.count() == 0:
        latest = page.locator("#palimpsest-blame").get_by_role("link", name=re.compile("return to latest|latest version", re.I))
    expect(latest.first).to_be_visible()
    latest.first.click()
    verify_article_snapshot(page, new_text, new_id)
    return new_id


def run_language(browser, language: str, language_state: dict, origin: str, auth: dict, run_id: str, screenshots: Path | None) -> int:
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    page = context.new_page()
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(15000)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    pages = language_state["pages"]
    cross = pages["cross_contributor_deletion"]
    cross_url = article_url(origin, cross["title"])
    page.goto(cross_url, wait_until="domcontentloaded")
    find_blame_link(page).click()
    expect(page).to_have_url(re.compile(r"[?&]action=blame(?:&|$)"))
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    verify_article_snapshot(page, load_fixture("cross_contributor_deletion")["revisions"][-1]["text"], cross["revisions"][-1]["revision_id"])
    wait_for_article_selection_ready(page, load_fixture("cross_contributor_deletion")["revisions"][-1]["text"])
    word = page.locator("#mw-content-text [data-pb-start]").filter(has_text=re.compile(r"^green$"))
    expect(word.first).to_be_visible()
    current_url = page.url
    word.first.click()
    expect(page.locator("#palimpsest-blame")).to_contain_text("green")
    if page.url != current_url:
        raise AssertionError("clicking an attributed word without a selection changed article navigation")
    exercise_selection(
        page,
        "cross_contributor_deletion",
        mobile=False,
        screenshot=screenshots / f"{language}-desktop.png" if screenshots else None,
    )

    chained = pages["chained_replacements"]
    page.goto(article_url(origin, chained["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    verify_article_snapshot(page, load_fixture("chained_replacements")["revisions"][-1]["text"], chained["revisions"][-1]["revision_id"])
    verify_replacement_timeline(page)
    verify_date_navigation(page, load_fixture("chained_replacements")["revisions"][-1]["text"], chained["revisions"][-1]["revision_id"])
    verify_recovery(page, load_fixture("chained_replacements")["revisions"][-1]["text"], chained["revisions"][-1]["revision_id"])

    repeated = pages["repeated_move_revert"]
    page.goto(article_url(origin, repeated["title"]) + "&action=blame", wait_until="domcontentloaded")
    verify_article_snapshot(page, load_fixture("repeated_move_revert")["revisions"][-1]["text"], repeated["revisions"][-1]["revision_id"])
    exercise_selection(page, "repeated_move_revert", mobile=False, screenshot=None)
    expect(page.locator("#palimpsest-blame")).to_contain_text(re.compile("ambiguous|uncertain", re.I))

    unicode_page = pages["unicode_utf16_selection"]
    page.goto(article_url(origin, unicode_page["title"]) + "&action=blame", wait_until="domcontentloaded")
    verify_article_snapshot(page, load_fixture("unicode_utf16_selection")["revisions"][-1]["text"], unicode_page["revisions"][-1]["revision_id"])
    exercise_selection(page, "unicode_utf16_selection", mobile=False, screenshot=None)

    verify_rendered_selection_cases(page, origin, language_state)

    partial_page = context.new_page()
    partial_page.set_default_timeout(5000)
    partial_page.set_default_navigation_timeout(15000)
    partial_page.on("pageerror", lambda error: page_errors.append(str(error)))
    verify_mouse_partial_selection(partial_page, origin, cross)

    mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    mobile = mobile_context.new_page()
    mobile.set_default_timeout(5000)
    mobile.set_default_navigation_timeout(15000)
    mobile.on("pageerror", lambda error: page_errors.append(str(error)))
    mobile.goto(article_url(origin, cross["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(mobile.locator("#palimpsest-blame")).to_be_visible()
    verify_mobile_layout(mobile)
    verify_article_snapshot(mobile, load_fixture("cross_contributor_deletion")["revisions"][-1]["text"], cross["revisions"][-1]["revision_id"])
    exercise_selection(
        mobile,
        "cross_contributor_deletion",
        mobile=True,
        screenshot=screenshots / f"{language}-mobile.png" if screenshots else None,
    )
    verify_mobile_layout(mobile)

    keyboard_page = context.new_page()
    keyboard_page.set_default_timeout(5000)
    keyboard_page.set_default_navigation_timeout(15000)
    keyboard_page.on("pageerror", lambda error: page_errors.append(str(error)))
    keyboard_page.goto(cross_url, wait_until="domcontentloaded")
    enter_blame_with_keyboard(keyboard_page)
    labels = keyboard_page.locator("#palimpsest-blame [aria-label], #palimpsest-blame [aria-labelledby]")
    if labels.count() == 0:
        raise AssertionError(f"{language}: Blame panel has no screen-reader labels")
    expect(labels.first).to_be_visible()
    verify_keyboard_phrase_activation(keyboard_page, "green", "Enter")
    verify_keyboard_phrase_activation(keyboard_page, "new", "Space")
    verify_concurrent_snapshot(keyboard_page, origin, language, auth, run_id)
    if page_errors:
        raise AssertionError(f"{language}: browser page JavaScript errors: {page_errors}")
    context.close()
    mobile_context.close()
    return 7


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    parser.add_argument("--screenshot-dir", type=Path)
    args = parser.parse_args()
    try:
        state = json.loads(args.state_file.read_text(encoding="utf-8"))
        auth = json.loads(args.auth_file.read_text(encoding="utf-8"))
        if state.get("scope") != "synthetic_only" or state.get("project") != "palimpsest-blame":
            raise ValueError("browser state is not from the authorized synthetic-only feature runtime")
        if auth.get("scope") != "synthetic_test_accounts_only" or auth.get("project") != "palimpsest-blame" or auth.get("run_id") != state.get("run_id"):
            raise ValueError("private accounts do not match this synthetic browser run")
        origins = {lang: os.environ.get(BASE_ORIGIN_ENV[lang]) for lang in LANGS}
        missing = [BASE_ORIGIN_ENV[lang] for lang, value in origins.items() if not value]
        if missing:
            raise ValueError("explicit browser host origins required: " + ", ".join(missing))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                total = 0
                for language in LANGS:
                    total += run_language(browser, language, state["languages"][language], origins[language], auth["languages"][language], state["run_id"], args.screenshot_dir)
                    print(f"PASS browser/{language}: desktop/mobile selection, inline history, keyboard action, date navigation")
                print(f"PASS browser: {total} language/viewport interaction groups")
            finally:
                browser.close()
    except Exception as exc:
        print(f"FAIL browser Blame acceptance: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

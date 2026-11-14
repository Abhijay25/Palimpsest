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


def load_fixture(fixture_id: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))


def article_url(origin: str, title: str) -> str:
    return f"{origin.rstrip('/')}/index.php?title={quote(title, safe=':') }"


def find_blame_link(page: Page):
    candidates = page.get_by_role("link", name=re.compile(r"\bBlame\b", re.I))
    expect(candidates.first).to_be_visible()
    return candidates.first


def enter_blame_with_keyboard(page: Page) -> None:
    for _ in range(48):
        active = page.evaluate("document.activeElement?.innerText || document.activeElement?.getAttribute('aria-label') || ''")
        if re.search(r"\bBlame\b", active, re.I):
            page.keyboard.press("Enter")
            break
        page.keyboard.press("Tab")
    else:
        raise AssertionError("keyboard tab order never reached a discoverable Blame link")
    expect(page).to_have_url(re.compile(r"[?&]action=blame(?:&|$)"))
    expect(page.locator("#palimpsest-blame")).to_be_visible()


def select_text(page: Page, quote: str, occurrence: int = 0) -> None:
    selected = page.evaluate(
        """({quote, occurrence}) => {
          const root = document.querySelector('#mw-content-text');
          if (!root) return null;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
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
          return {text: selection.toString(), start: begin, end: finish};
        }""",
        {"quote": quote, "occurrence": occurrence},
    )
    if not selected or selected["text"] != quote:
        raise AssertionError(f"could not select exact unique text {quote!r} from the rendered article")


def inspect_selected_text(page: Page, mobile: bool) -> None:
    if mobile:
        button = page.get_by_role("button", name=re.compile(r"inspect (selected text|selection)|analyze selection", re.I))
        expect(button).to_be_visible()
        button.tap()
        # Mobile browsers may drop the native Range when the inspect button is
        # tapped. The component must retain the user quote it captured earlier.
        page.evaluate("window.getSelection()?.removeAllRanges()")


def verify_inline_panel(page: Page, quote: str) -> None:
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text(quote)
    geometry = page.evaluate(
        """(quote) => {
          const panel = document.querySelector('#palimpsest-blame');
          const root = document.querySelector('#mw-content-text');
          if (!panel || !root) return null;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          const nodes = []; let full = '';
          while (walker.nextNode()) { nodes.push({node: walker.currentNode, start: full.length}); full += walker.currentNode.nodeValue || ''; }
          const begin = full.indexOf(quote);
          if (begin < 0 || full.indexOf(quote, begin + 1) >= 0) return null;
          const locate = (offset, isEnd) => {
            for (const item of nodes) {
              const length = item.node.nodeValue.length;
              if (offset >= item.start && (offset < item.start + length || (isEnd && offset === item.start + length))) return {node: item.node, offset: offset - item.start};
            }
            return null;
          };
          const start = locate(begin, false), end = locate(begin + quote.length, true);
          if (!start || !end) return null;
          const range = document.createRange(); range.setStart(start.node, start.offset); range.setEnd(end.node, end.offset);
          const statement = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
            ? range.commonAncestorContainer.closest('p,li,td,blockquote')
            : range.commonAncestorContainer.parentElement?.closest('p,li,td,blockquote');
          if (!statement || !root.contains(panel)) return null;
          const sr = statement.getBoundingClientRect(), pr = panel.getBoundingClientRect();
          return {statementBottom: sr.bottom, panelTop: pr.top, below: pr.top >= sr.bottom - 2};
        }""",
        quote,
    )
    if not geometry or not geometry["below"]:
        raise AssertionError("inline breakdown is not rendered below the selected statement")


def verify_article_snapshot(page: Page, expected_visible_text: str, revision_id: int) -> None:
    content = page.locator("#mw-content-text")
    expect(content).to_be_visible()
    expect(content).to_contain_text(expected_visible_text)
    rendered_revision = page.evaluate("window.mw?.config?.get('wgRevisionId')")
    if int(rendered_revision or -1) != int(revision_id):
        raise AssertionError(f"rendered article revision {rendered_revision!r} differs from expected local revision {revision_id}")


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


def verify_replacement_timeline(page: Page) -> None:
    doc = load_fixture("chained_replacements")
    select_text(page, doc["expected"]["selection"]["text"])
    inspect_selected_text(page, mobile=False)
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text("quick")
    expect(panel).to_contain_text("slow")
    expect(panel).to_contain_text("fast")
    expect(panel).to_contain_text("old")
    compare = panel.get_by_role("button", name=re.compile("compare with previous revision", re.I))
    if compare.count() == 0:
        compare = panel.get_by_role("link", name=re.compile("compare with previous revision", re.I))
    expect(compare.first).to_be_visible()
    changes = panel.get_by_role("link", name=re.compile("view editor.?s changes", re.I))
    expect(changes.first).to_be_visible()
    with page.expect_navigation(wait_until="domcontentloaded"):
        changes.first.click()
    if "action=blame" in page.url or not re.search(r"(?:[?&](?:diff|oldid)=|Special:Diff)", page.url):
        raise AssertionError(f"core revision comparison link did not open a MediaWiki diff: {page.url}")
    page.go_back(wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()


def date_text_tomorrow_utc() -> str:
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return tomorrow.strftime("%-d %B %Y")


def verify_date_navigation(page: Page, expected_latest_text: str, latest_revision_id: int) -> None:
    panel = page.locator("#palimpsest-blame")
    date_input = panel.get_by_role("textbox", name=re.compile("date", re.I))
    expect(date_input).to_be_visible()
    tomorrow = date_text_tomorrow_utc()
    date_input.fill(f"Latest version before {tomorrow}")
    apply = panel.get_by_role("button", name=re.compile("find|apply|show version|go", re.I)).last
    apply.click()
    expect(panel).to_contain_text("UTC")
    expect(page.locator("#mw-content-text")).to_contain_text(expected_latest_text)
    if int(page.evaluate("window.mw?.config?.get('wgRevisionId')") or -1) != int(latest_revision_id):
        raise AssertionError("latest-before query did not synchronize the article revision")

    date_input.fill("As of 15 March 2026")
    apply.click()
    expect(panel).to_contain_text(re.compile("before the earliest|no version|no revision", re.I))

    date_input.fill(f"Between 1 January and {tomorrow}")
    apply.click()
    range_result = panel.get_by_role("button", name=re.compile(str(latest_revision_id)))
    if range_result.count() == 0:
        range_result = panel.get_by_role("link", name=re.compile(str(latest_revision_id)))
    expect(range_result.first).to_be_visible()
    range_result.first.click()
    if int(page.evaluate("window.mw?.config?.get('wgRevisionId')") or -1) != int(latest_revision_id):
        raise AssertionError("choosing a range result did not synchronize article and attribution revisions")
    invalid_inputs = (
        ("2026-03-15T12:99:00Z", re.compile("invalid.*(time|minute)|(time|minute).*invalid", re.I)),
        ("Between 31 March and 1 February 2026", re.compile("invalid|reversed|range", re.I)),
    )
    for value, expected_error in invalid_inputs:
        date_input.fill(value)
        apply.click()
        expect(panel).to_contain_text(expected_error)


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
    expect(page).to_have_url(re.compile(r"[?&]title=" + re.escape(quote(target["title"], safe=":"))))
    verify_article_snapshot(page, mapped_fixture["link_target_text"], target["revision_id"])
    if "action=blame" in page.url:
        raise AssertionError("ordinary article link was intercepted by the Blame selection UI")

    generated = browser_pages["generated_unmapped_selection"]
    generated_fixture = load_fixture("generated_unmapped_selection")
    page.goto(article_url(origin, generated["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    verify_article_snapshot(page, "The mapped prefix UNMAPPED_SENTINEL mapped suffix.", generated["revision_id"])
    quote = generated_fixture["selection_text_template"]
    select_text(page, quote)
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text(quote)
    verify_inline_panel(page, quote)
    if not re.search(r"unmapped|partial|unsupported|not attributable", panel.inner_text(), re.I):
        raise AssertionError("mixed mapped/generated selection has no explicit partial-coverage explanation")
    annotated = page.evaluate(
        """(sentinel) => {
          const root = document.querySelector('#mw-content-text');
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
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
    select_text(page, full_quote)
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text(full_quote)
    verify_inline_panel(page, full_quote)
    if len(fragment_fixture["tokens"]) <= 64:
        raise AssertionError("fragmented selection fixture no longer exceeds the known 64-fragment regression threshold")

    paragraph = browser_pages["paragraph_boundary_selection"]
    paragraph_fixture = load_fixture("paragraph_boundary_selection")
    page.goto(article_url(origin, paragraph["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#mw-content-text")).to_be_visible()
    if int(page.evaluate("window.mw?.config?.get('wgRevisionId')") or -1) != int(paragraph["revision_id"]):
        raise AssertionError("paragraph-boundary fixture rendered a different local revision")
    select_text(page, paragraph_fixture["selection_text"])
    expect(page.locator("#palimpsest-blame")).to_contain_text(paragraph_fixture["selection_text"])


def verify_mouse_partial_selection(page: Page, origin: str, cross: dict) -> None:
    page.goto(article_url(origin, cross["title"]) + "&action=blame", wait_until="domcontentloaded")
    expect(page.locator("#palimpsest-blame")).to_be_visible()
    coordinates = page.evaluate(
        """() => {
          const root = document.querySelector('#mw-content-text');
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const text = walker.currentNode.nodeValue || '', word = 'green', at = text.indexOf(word);
            if (at < 0) continue;
            const range = document.createRange(); range.setStart(walker.currentNode, at + 1); range.setEnd(walker.currentNode, at + 4);
            const rect = range.getBoundingClientRect();
            return {startX: rect.left + 0.25, endX: rect.right - 0.25, y: rect.top + rect.height / 2};
          }
          return null;
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
    inspect = page.get_by_role("button", name=re.compile(r"inspect (selected text|selection)|analyze selection", re.I))
    expect(inspect).to_be_visible()
    inspect.click()
    panel = page.locator("#palimpsest-blame")
    expect(panel).to_contain_text("ree")
    page.evaluate("window.getSelection()?.removeAllRanges()")
    expect(panel).to_contain_text("ree")
    if not any(item == {"start": 13, "end": 16} for item in requested_ranges):
        raise AssertionError(f"partial-word analysis did not send exact source offsets 13..16: {requested_ranges}")


def verify_concurrent_snapshot(page: Page, origin: str, language: str, language_state: dict, auth: dict, run_id: str) -> int:
    page_state = language_state["pages"]["cross_contributor_deletion"]
    fixture_doc = load_fixture("cross_contributor_deletion")
    old_id = page_state["revisions"][-1]["revision_id"]
    old_text = fixture_doc["revisions"][-1]["text"]
    page.goto(article_url(origin, page_state["title"]) + "&action=blame", wait_until="domcontentloaded")
    verify_article_snapshot(page, old_text, old_id)
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
    editor = WikiApi(origin.rstrip("/") + "/api.php")
    editor.login(auth["username"], auth["password"])
    new_id = editor.edit(page_state["title"], new_text, f"[synthetic Blame concurrency {run_id}]")

    quote = load_fixture("cross_contributor_deletion")["expected"]["selection"]["text"]
    select_text(page, quote)
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
    verify_article_snapshot(mobile, load_fixture("cross_contributor_deletion")["revisions"][-1]["text"], cross["revisions"][-1]["revision_id"])
    exercise_selection(
        mobile,
        "cross_contributor_deletion",
        mobile=True,
        screenshot=screenshots / f"{language}-mobile.png" if screenshots else None,
    )

    keyboard_page = context.new_page()
    keyboard_page.set_default_timeout(5000)
    keyboard_page.set_default_navigation_timeout(15000)
    keyboard_page.on("pageerror", lambda error: page_errors.append(str(error)))
    keyboard_page.goto(cross_url, wait_until="domcontentloaded")
    enter_blame_with_keyboard(keyboard_page)
    labels = keyboard_page.locator("#palimpsest-blame [aria-label], #palimpsest-blame [aria-labelledby]")
    if labels.count() == 0:
        raise AssertionError(f"{language}: Blame panel has no screen-reader labels")
    keyboard_page.keyboard.press("Escape")
    verify_concurrent_snapshot(keyboard_page, origin, language, language_state, auth, run_id)
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

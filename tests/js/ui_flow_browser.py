"""Browser smoke test for the ResourceLoader UI with a contract-valid API stub."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "infra/wiki/extensions/PalimpsestBlame/resources"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame" data-revision="91"></div></div></main>')
        page.evaluate(
            """() => {
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 0, wgArticleId: 42, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: (title, params) => '/wiki/' + title + '?' + new URLSearchParams(params) },
                    user: { tokens: { get: () => '+\\\\' } }
                };
                const revision = (id, parent, comment) => ({ revision_id: id, parent_id: parent, timestamp: id === 91 ? '2025-12-31T23:59:59Z' : '2025-12-30T23:59:59Z', user: 'Editor', comment, minor: false, source: null, url: '/wiki/Example?oldid=' + id, diff_url: '/w/index.php?diff=' + id + '&oldid=' + parent, contributions_url: '/wiki/Special:Contributions/Editor' });
                const base = {
                    status: 'ready', page: { id: 42, title: 'Example', language: 'en', latest_revision_id: 91 },
                    snapshot: { revision_id: 91, parent_id: 90, timestamp: '2025-12-31T23:59:59Z', user: 'Editor', comment: 'Changed phrase', url: '/wiki/Example?oldid=91', diff_url: '/w/index.php?diff=91&oldid=90', contributions_url: '/wiki/Special:Contributions/Editor' },
                    coverage: { history_complete: false, provenance_status: 'verified', source_wiki: 'enwiki', source_page_id: 99, source_anchor_revision_id: 91, source_anchor_timestamp: '2025-12-31T23:59:59Z', earliest_timestamp: '2025-01-01T00:00:00Z', latest_timestamp: '2025-12-31T23:59:59Z', reasons: ['Imported source history ends at the source anchor.'] },
                    source_text: 'alpha beta', html: '<p id="statement"><span data-pb-start="0" data-pb-end="5">alpha</span> <span data-pb-start="6" data-pb-end="10">beta</span></p>',
                    spans: [{ start: 0, end: 5, revision_id: 91, token_id: '91:0', lineage_ids: [], confidence: 'certain' }, { start: 6, end: 10, revision_id: 91, token_id: '91:1', lineage_ids: [], confidence: 'certain' }],
                    revisions: [revision(91, 90, 'Changed phrase'), revision(90, 89, 'Old text')],
                    events: [{ revision_id: 90, before: 'unrelated page edit', after: 'unrelated page edit', token_ids: ['90:0'], ambiguous: false }],
                    algorithm: { version: 'fixture-v1', semantics: 'last-change', limits: {} }, mapping: { mapped_characters: 9, unmapped_reasons: [] }
                };
                window.__fixtureBase = base;
                window.__requests = [];
                window.__forceUnavailable = false;
                window.__forcePermanent = false;
                window.__pendingMismatch = false;
                window.__buildComplete = false;
                window.fetch = (input, init = {}) => {
                    const method = init.method || 'GET';
                    const url = new URL(String(input), location.href);
                    const params = new URLSearchParams(method === 'GET' ? url.search : init.body);
                    window.__requests.push({ method, params: Object.fromEntries(params.entries()) });
                    let response;
                    if (params.get('op') === 'build' && method === 'POST') {
                        window.__buildComplete = true;
                        response = { status: 'pending', revision_id: 91, buildable: true, job: { id: 'job-1', revision_id: 91, status: 'pending', processed: 0, total: 2 } };
                    } else if (params.get('op') === 'status') {
                        if (params.get('revision') !== '91' || !params.get('jobid')) {
                            return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({ error: { info: 'status requires the exact pinned revision and job ID' } }) });
                        }
                        response = Object.assign({}, base, { revision_id: 91, job: { id: params.get('jobid'), revision_id: 91, status: 'ready', processed: 2, total: 2 } });
                    } else if (params.get('op') === 'analyze' && params.get('ranges') && window.__pendingMismatch) {
                        response = { status: 'pending', revision_id: 92, buildable: true, job: { id: 'wrong-revision-job', revision_id: 92, status: 'pending' } };
                    } else if (params.get('op') === 'analyze' && window.__forcePermanent && !window.__buildComplete) {
                        response = { status: 'unavailable', reason: 'Imported provenance mapping is invalid.', buildable: false };
                    } else if (params.get('op') === 'analyze' && window.__forceUnavailable && !window.__buildComplete) {
                        response = { status: 'unavailable', reason: 'Fixture exceeds synchronous analysis limits.', buildable: true };
                    } else if (params.get('op') === 'versions') {
                        response = { status: 'ready', mode: params.get('mode'), bounds: { from: params.get('from'), to: params.get('to') }, versions: [
                            { revision_id: 91, timestamp: '2025-12-31T23:59:59Z', user: 'Editor' },
                            { revision_id: 90, timestamp: '2025-12-30T23:59:59Z', user: 'Imported>SourceWiki' },
                            { revision_id: 89, timestamp: '2025-12-29T23:59:59Z', user: 'Importer', source_user: 'Source Editor', source_snapshot: { revision_id: 789 } }
                        ], selected_revision_id: 91, continuation: null, coverage: base.coverage };
                    } else if (params.get('ranges')) {
                        response = Object.assign({}, base, { selection: { ranges: JSON.parse(params.get('ranges')), revision_ids: [91], events: [{ revision_id: 91, before: 'old phrase', after: 'lph', token_ids: ['91:0'], ambiguous: false }], ambiguous: false, reasons: [] } });
                    } else {
                        response = base;
                    }
                    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ palimpsestblame: response }) });
                };
            }"""
        )
        page.add_script_tag(path=str(RESOURCE / "helpers.js"))
        page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))

        page.wait_for_selector(".pb-date-query")
        assert page.evaluate("window.__requests.find(r => r.params.op === 'analyze').params.revision") == "91", "the action element's data-revision must pin the first analysis"
        assert page.locator("#mw-content-text > .mw-parser-output").count() == 1, "action-only page must receive a peer article container"
        assert "alpha beta" in page.locator(".mw-parser-output").inner_text()

        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.pbStart") == "0", "Tab should reach the first attributed phrase"
        page.keyboard.press("Enter")
        page.wait_for_selector(".pb-breakdown")
        assert page.evaluate("document.activeElement.classList.contains('pb-close')"), "opening a breakdown should focus its Close history control"
        page.keyboard.press("Escape")
        assert page.locator(".pb-breakdown").count() == 0
        assert page.evaluate("document.activeElement.dataset.pbStart") == "0", "Escape should return focus to the phrase that opened history"
        page.evaluate("window.__escapePrevented = null; document.addEventListener('keydown', event => { if (event.key === 'Escape') window.__escapePrevented = event.defaultPrevented; });")
        page.keyboard.press("Escape")
        assert page.evaluate("window.__escapePrevented") is False, "Escape without an active breakdown must not be intercepted"

        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.pbStart") == "6", "Tab should advance to the second attributed phrase"
        page.keyboard.press("Space")
        page.wait_for_selector(".pb-breakdown")
        page.evaluate(
            """() => {
                const oldPhrase = document.querySelector('[data-pb-start="6"]');
                const replacement = oldPhrase.cloneNode(true);
                oldPhrase.replaceWith(replacement);
                window.__freshPhrase = replacement;
            }"""
        )
        page.keyboard.press("Escape")
        assert page.locator(".pb-breakdown").count() == 0
        assert page.evaluate("document.activeElement === window.__freshPhrase"), "Escape should resolve focus to the fresh phrase node with the same verified range"

        drag_points = page.evaluate(
            """() => {
                const text = document.querySelector('[data-pb-start="0"]').firstChild;
                const charRect = index => {
                    const range = document.createRange();
                    range.setStart(text, index);
                    range.setEnd(text, index + 1);
                    const rect = range.getBoundingClientRect();
                    return { left: rect.left, right: rect.right, y: rect.top + rect.height / 2 };
                };
                const first = charRect(1), last = charRect(3);
                return { startX: first.left + 0.2, endX: last.right - 0.2, y: first.y };
            }"""
        )
        page.mouse.move(drag_points["startX"], drag_points["y"])
        page.mouse.down()
        page.mouse.move(drag_points["endX"], drag_points["y"], steps=8)
        page.mouse.up()
        assert page.evaluate("window.getSelection().toString()") == "lph"
        page.wait_for_selector(".pb-breakdown")
        assert page.locator(".pb-selected-text").inner_text() == "lph"
        assert page.locator(".pb-timeline").inner_text().find("unrelated page edit") == -1
        assert page.locator(".pb-coverage").count() == 1, "selection view must show coverage once"
        assert page.get_by_role("link", name="Return to latest version").count() == 1
        assert page.locator("#palimpsest-blame").evaluate("node => Array.from(node.children).indexOf(node.querySelector('.pb-breakdown')) < Array.from(node.children).indexOf(node.querySelector('.pb-date-query'))"), "selection details must precede the secondary date query"
        assert page.locator("#palimpsest-blame").evaluate("node => node.previousElementSibling.id") == "statement", "history panel must sit directly after the selected statement"
        sent_ranges = page.evaluate("window.__requests.filter(r => r.params.ranges).at(-1).params.ranges")
        assert sent_ranges == '[{"start":1,"end":4}]', sent_ranges

        page.get_by_role("button", name="Close history").click()
        page.evaluate(
            """() => {
                const generated = document.createElement('span');
                generated.textContent = 'PURE_GENERATED';
                document.querySelector('.mw-parser-output p').append(generated);
                const range = document.createRange();
                range.selectNodeContents(generated.firstChild);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )
        analyze_count = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        page.get_by_role("button", name="Inspect selected article text").click()
        assert "no verified source offsets" in page.get_by_role("alert").inner_text()
        assert page.locator(".pb-selected-text").text_content() == "PURE_GENERATED"
        assert page.locator(".pb-breakdown").count() == 0
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analyze_count
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))")
        page.evaluate("document.querySelector('.mw-parser-output p span:last-child').remove()")

        mixed_selection = page.evaluate(
            """() => {
                const alpha = document.querySelector('[data-pb-start="0"]');
                const beta = document.querySelector('[data-pb-start="6"]');
                alpha.after(document.createTextNode('UNMAPPED_SENTINEL'));
                const selection = window.getSelection();
                selection.setBaseAndExtent(alpha.firstChild, 0, beta.firstChild, 4);
                const snapshot = window.PalimpsestBlameHelpers.selectionRanges(selection);
                return { quote: snapshot.exactText, ranges: snapshot.ranges, unmapped: snapshot.unmapped };
            }"""
        )
        assert "UNMAPPED_SENTINEL" in mixed_selection["quote"]
        assert mixed_selection["ranges"] == [{"start": 0, "end": 5}, {"start": 6, "end": 10}]
        assert any("UNMAPPED_SENTINEL" in item["text"] for item in mixed_selection["unmapped"])
        analyze_count = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        page.get_by_role("button", name="Inspect selected article text").click()
        first_guard_message = page.get_by_role("alert").inner_text()
        assert "No partial attribution was requested" in first_guard_message, first_guard_message
        assert page.locator(".pb-selected-text").text_content() == mixed_selection["quote"]
        assert page.locator(".pb-breakdown").count() == 0
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))"), "incomplete-selection feedback must remain outside article content"
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analyze_count

        phrase_quote = page.evaluate(
            """() => {
                const alpha = document.querySelector('[data-pb-start="0"]');
                const beta = document.querySelector('[data-pb-start="6"]');
                const selection = window.getSelection();
                selection.setBaseAndExtent(alpha.firstChild, 0, beta.firstChild, 4);
                return selection.toString();
            }"""
        )
        page.locator('[data-pb-start="0"]').click()
        assert "No partial attribution was requested" in page.get_by_role("alert").inner_text()
        assert page.locator(".pb-selected-text").text_content() == phrase_quote
        assert page.locator(".pb-breakdown").count() == 0
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analyze_count, "phrase activation must share the unmapped-text analysis guard"
        page.evaluate(
            """() => {
                const walker = document.createTreeWalker(document.querySelector('.mw-parser-output'), NodeFilter.SHOW_TEXT);
                let text;
                while ((text = walker.nextNode())) {
                    if (text.nodeValue === 'UNMAPPED_SENTINEL') text.remove();
                }
            }"""
        )
        page.evaluate(
            """() => {
                const selection = window.getSelection();
                const alpha = document.querySelector('[data-pb-start="0"]').firstChild;
                selection.setBaseAndExtent(alpha, 0, alpha, 5);
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")
        assert page.locator(".pb-selected-text").text_content() == "alpha"
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analyze_count + 1, "a fully mapped selection must recover and analyze normally after the guard"
        page.get_by_role("button", name="Close history").click()
        page.evaluate("window.getSelection().removeAllRanges()")
        recovery_count = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        page.get_by_role("button", name="Inspect selected article text").click()
        assert "Select text in the article first" in page.get_by_role("alert").inner_text()
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == recovery_count
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))")

        page.evaluate(
            """() => {
                const article = document.querySelector('.mw-parser-output');
                const alpha = article.querySelector('[data-pb-start="0"]');
                const beta = article.querySelector('[data-pb-start="6"]');
                alpha.closest('p').id = 'paragraph-one';
                const second = document.createElement('p');
                second.id = 'paragraph-two';
                second.append(beta);
                document.getElementById('paragraph-one').after(document.createTextNode('\\n'), second);
                article.parentNode.insertBefore(document.getElementById('palimpsest-blame'), article.nextSibling);
            }"""
        )
        for reverse in [False, True]:
            native_selection = page.evaluate(
                """reverse => {
                    const selection = window.getSelection();
                    const alpha = document.querySelector('[data-pb-start="0"]').firstChild;
                    const beta = document.querySelector('[data-pb-start="6"]').firstChild;
                    if (reverse) selection.setBaseAndExtent(beta, 2, alpha, 1);
                    else selection.setBaseAndExtent(alpha, 1, beta, 2);
                    return { quote: selection.toString(), snapshot: window.PalimpsestBlameHelpers.selectionRanges(selection) };
                }""",
                reverse,
            )
            native_quote = native_selection["quote"]
            assert native_selection["snapshot"]["unmapped"] == [], native_selection["snapshot"]["unmapped"]
            page.get_by_role("button", name="Inspect selected article text").click()
            page.wait_for_selector(".pb-breakdown")
            actual_quote = page.locator(".pb-selected-text").text_content()
            assert actual_quote == native_quote, f"the inline quote must preserve the exact native cross-paragraph selection: {actual_quote!r} != {native_quote!r}"
            assert page.locator("#palimpsest-blame").evaluate("node => node.previousElementSibling.id") == "paragraph-two", "forward and reverse selections must place the panel after the last selected block"
            assert page.locator(".pb-selection-incomplete").count() == 0, "inter-paragraph whitespace must not invalidate mapped text"
            assert page.evaluate("window.__requests.filter(r => r.params.ranges).at(-1).params.ranges") == '[{"start":1,"end":5},{"start":6,"end":8}]', "mapped ranges on both sides of a newline must remain available"
            page.get_by_role("button", name="Close history").click()

        boundary_quote = page.evaluate(
            """() => {
                const selection = window.getSelection();
                const alpha = document.querySelector('[data-pb-start="0"]').firstChild;
                const beta = document.querySelector('[data-pb-start="6"]').firstChild;
                selection.setBaseAndExtent(alpha, 1, beta, 0);
                return selection.toString();
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")
        assert page.locator(".pb-selected-text").text_content() == boundary_quote
        assert page.locator("#palimpsest-blame").evaluate("node => node.previousElementSibling.id") == "paragraph-one", "an endpoint at offset zero must anchor to the preceding selected block"
        page.get_by_role("button", name="Close history").click()
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))"), "closing history must restore the panel outside article content"

        page.evaluate(
            """() => {
                const selection = window.getSelection();
                const beta = document.querySelector('[data-pb-start="6"]').firstChild;
                selection.setBaseAndExtent(beta, 0, beta, 4);
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")
        assert page.locator("#palimpsest-blame").evaluate("node => node.previousElementSibling.id") == "paragraph-two"

        page.get_by_role("textbox", name="Describe a date query").fill("Latest version before 1 April 2026")
        page.get_by_role("button", name="Interpret date query").click()
        assert "2026-04-01T00:00:00Z" in page.locator(".pb-date-preview").inner_text()
        assert "does not prove the live source wiki’s state" in page.locator(".pb-date-preview").inner_text()
        page.get_by_role("button", name="Apply these bounds").click()
        page.wait_for_selector(".pb-version")
        assert page.locator(".pb-breakdown").count() == 1, "date search must remain usable without closing the selection breakdown"
        labels = page.locator(".pb-version").all_inner_texts()
        assert any("Local editor: Editor" in label for label in labels), labels
        assert any("Local import account: Imported>SourceWiki" in label and "source editor unavailable" in label for label in labels), labels
        assert any("Source editor: Source Editor" in label and "source snapshot 789" in label for label in labels), labels
        versions_request = page.evaluate("window.__requests.filter(r => r.params.op === 'versions').at(-1)")
        assert versions_request["params"]["mode"] == "before"
        assert versions_request["params"]["to"] == "2026-04-01T00:00:00Z"

        analysis_count = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        page.evaluate(
            """() => {
                const selection = window.getSelection();
                const alpha = document.querySelector('[data-pb-start="0"]').firstChild;
                const controlText = document.querySelector('.pb-date-query p.pb-muted').firstChild;
                selection.setBaseAndExtent(alpha, 1, controlText, Math.min(5, controlText.length));
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        assert "crosses the inline history controls" in page.get_by_role("alert").inner_text()
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analysis_count, "selections crossing the inline controls must not request partial analysis"
        assert page.locator(".pb-breakdown").count() == 1, "the Close history action must remain available after a guarded selection"
        page.get_by_role("button", name="Close history").click()
        assert page.locator(".pb-breakdown").count() == 0
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))")
        assert page.get_by_role("textbox", name="Describe a date query").count() == 1, "closing history must restore the full date controls"
        assert page.get_by_role("link", name="Return to latest version").count() == 1, "closing history must restore the latest-version link"

        page.evaluate(
            """() => {
                const block = document.createElement('p');
                block.id = 'too-fragmented';
                for (let i = 0; i < 65; i++) {
                    const span = document.createElement('span');
                    span.dataset.pbStart = String(100 + i * 2);
                    span.dataset.pbEnd = String(101 + i * 2);
                    span.textContent = 'x';
                    block.append(span, document.createTextNode(' '));
                }
                document.querySelector('.mw-parser-output').append(block);
                const range = document.createRange();
                range.setStart(block.firstChild.firstChild, 0);
                range.setEnd(block.children[64].firstChild, 1);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )
        analysis_count = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        limit_quote = page.evaluate("window.getSelection().toString()")
        page.get_by_role("button", name="Inspect selected article text").click()
        assert "no partial analysis was requested" in page.get_by_text("This selection contains more than 64 separate verified source ranges.").inner_text()
        assert page.locator(".pb-selected-text").text_content() == limit_quote
        page.evaluate("window.getSelection().removeAllRanges()")
        assert page.locator(".pb-selected-text").text_content() == limit_quote, "the unsupported selection quote must survive native selection clearing"
        assert page.locator(".pb-breakdown").count() == 0
        assert page.locator("#mw-content-text").evaluate("content => content.contains(document.getElementById('palimpsest-blame')) && !document.querySelector('.mw-parser-output').contains(document.getElementById('palimpsest-blame'))")
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analysis_count

        status_count = page.evaluate("window.__requests.filter(r => r.params.op === 'status').length")
        page.evaluate("window.__pendingMismatch = true")
        page.locator('[data-pb-start="0"]').click()
        assert "targets revision 92" in page.get_by_role("alert").inner_text()
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'status').length") == status_count, "mismatched pending work must never be polled"

        page.evaluate("window.__pendingMismatch = false; window.__forcePermanent = true")
        page.locator('[data-pb-start="0"]').click()
        page.wait_for_selector("[role=alert]")
        assert page.get_by_role("button", name="Prepare attribution").count() == 0

        page.evaluate("window.__forcePermanent = false; window.__forceUnavailable = true")
        page.locator('[data-pb-start="0"]').click()
        analyze_before_build = page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length")
        page.get_by_role("button", name="Prepare attribution").click()
        page.wait_for_selector(".pb-date-query")
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analyze_before_build, "a ready status response with full analysis must be rendered without repeating synchronous analysis"
        build_request = page.evaluate("window.__requests.filter(r => r.params.op === 'build').at(-1)")
        status_request = page.evaluate("window.__requests.filter(r => r.params.op === 'status').at(-1)")
        assert build_request["method"] == "POST"
        assert build_request["params"]["token"] == "+\\", "the valid anonymous CSRF token must reach POST unchanged"
        assert status_request["params"]["jobid"] == "job-1"
        assert status_request["params"]["revision"] == "91", "every status request must include the pinned target revision"
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').at(-1).params.revision") == "91", "selection and retry analysis must stay pinned to the original snapshot"

        fixture = page.evaluate("window.__fixtureBase")
        touch_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        touch_page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame"></div></div></main>')
        touch_page.evaluate(
            """base => {
                base.source_text = 'alphabeta';
                base.html = '<p id="statement"><span data-pb-start="0" data-pb-end="5">alpha</span><span data-pb-start="5" data-pb-end="9">beta</span></p>';
                base.spans = [{ start: 0, end: 9, revision_id: 91, token_id: '91:0', token_ranges: [[0, 5, '91:0'], [5, 9, '91:1']], lineage_ids: ['shared:ancestor', '91:0', '91:1'], confidence: 'certain' }];
                base.events = [
                    { revision_id: 90, before: 'left-word-only event', after: 'alpha', token_ids: ['91:0'], ambiguous: false },
                    { revision_id: 91, before: 'right-word event', after: 'beta', token_ids: ['91:1'], ambiguous: false },
                    { revision_id: 92, before: '', after: 'inserted beside beta', left_token_id: '91:1', token_ids: [], ambiguous: false },
                    { revision_id: 89, before: 'deleted beside beta', after: '', left_token_id: '91:1', token_ids: [], ambiguous: false },
                    { revision_id: 88, before: 'replaced beside beta', after: 'replacement', right_token_id: '91:1', token_ids: [], ambiguous: true }
                ];
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 0, wgArticleId: 42, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: (title, params) => '/wiki/' + title + '?' + new URLSearchParams(params) },
                    user: { tokens: { get: () => '+\\\\' } }
                };
                window.__requests = [];
                window.__initialPending = true;
                window.__selectionPending = false;
                window.fetch = (input, init = {}) => {
                    const params = new URLSearchParams(new URL(String(input), location.href).search);
                    window.__requests.push(Object.fromEntries(params.entries()));
                    let response;
                    if (params.get('op') === 'status') {
                        if (params.get('revision') !== '91') {
                            return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({ error: { info: 'status requires revision 91' } }) });
                        }
                        response = Object.assign({}, base, { revision_id: 91, job: { id: params.get('jobid'), revision_id: 91, status: 'ready' } });
                    } else if (params.get('op') === 'analyze' && window.__initialPending) {
                        window.__initialPending = false;
                        response = { status: 'pending', revision_id: 91, job: { id: 'initial-job', revision_id: 91, status: 'pending' } };
                    } else if (params.get('op') === 'analyze' && params.get('ranges') && window.__selectionPending) {
                        window.__selectionPending = false;
                        response = { status: 'pending', revision_id: 91, job: { id: 'selection-job', revision_id: 91, status: 'pending' } };
                    } else if (params.get('ranges')) {
                        response = Object.assign({}, base, { selection: { ranges: JSON.parse(params.get('ranges')), revision_ids: [91], events: [{ revision_id: 91, before: 'old', after: 'lph', token_ids: ['91:0'], ambiguous: false }], ambiguous: false, reasons: [] } });
                    } else {
                        response = base;
                    }
                    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ palimpsestblame: response }) });
                };
            }""",
            fixture,
        )
        touch_page.add_script_tag(path=str(RESOURCE / "helpers.js"))
        touch_page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))
        touch_page.wait_for_selector(".pb-date-query")
        initial_status = touch_page.evaluate("window.__requests.filter(r => r.op === 'status').at(-1)")
        assert initial_status["revision"] == "91", "a pending initial response must pin the job revision before polling"
        touch_page.evaluate(
            """() => {
                window.__selectionPending = true;
                const text = document.querySelector('[data-pb-start="5"]').firstChild;
                const range = document.createRange();
                range.setStart(text, 1);
                range.setEnd(text, 3);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )
        touch_button = touch_page.get_by_role("button", name="Inspect selected article text")
        touch_box = touch_button.bounding_box()
        touch_page.touchscreen.tap(touch_box["x"] + touch_box["width"] / 2, touch_box["y"] + touch_box["height"] / 2)
        touch_page.wait_for_selector(".pb-breakdown")
        assert touch_page.locator(".pb-selected-text").inner_text() == "et"
        assert touch_page.locator(".pb-event").count() == 3, "selected token events and before-bearing changes anchored to it should match"
        touch_page.locator('.pb-event[data-pb-revision-id="91"] summary').click()
        timeline = touch_page.locator(".pb-timeline").inner_text()
        assert "right-word event" in timeline, timeline
        assert touch_page.locator('.pb-event[data-pb-revision-id="89"]').count() == 1, "the selected-word deletion anchor should remain in focused history"
        assert touch_page.locator('.pb-event[data-pb-revision-id="88"]').count() == 1, "the selected-word replacement anchor should remain in focused history"
        assert "inserted beside beta" not in timeline, "insertions next to selected words must not be included by anchor alone"
        assert "left-word-only event" not in timeline, "a partial selection in a coalesced span must exclude sibling token events"
        assert touch_page.evaluate("window.__requests.filter(r => r.ranges).at(-1).ranges") == '[{"start":6,"end":8}]'
        touch_page.close()

        conflict_page = browser.new_page()
        conflict_page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame" data-revision="91"></div></div></main>')
        conflict_page.evaluate(
            """() => {
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 92, wgArticleId: 42, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: () => '/wiki/Example' }
                };
                window.__requests = 0;
                window.fetch = () => { window.__requests++; return Promise.reject(new Error('unexpected API request')); };
            }"""
        )
        conflict_page.add_script_tag(path=str(RESOURCE / "helpers.js"))
        conflict_page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))
        assert "pinned to revision 91" in conflict_page.get_by_role("alert").inner_text()
        assert conflict_page.evaluate("window.__requests") == 0, "conflicting action and page revisions must block API analysis"
        conflict_page.close()

        malformed_fixture = dict(fixture)
        malformed_fixture["spans"] = [{
            "start": 0, "end": 5, "revision_id": 91, "token_id": "91:0",
            "token_ranges": [[0, 2, "91:0"], [3, 5, "91:1"]],
            "lineage_ids": ["91:0", "91:1"], "confidence": "certain"
        }]
        invalid_page = browser.new_page()
        invalid_page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame" data-revision="91"></div></div></main>')
        invalid_page.evaluate(
            """response => {
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 91, wgArticleId: 42, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: () => '/wiki/Example' }
                };
                window.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ palimpsestblame: response }) });
            }""",
            malformed_fixture,
        )
        invalid_page.add_script_tag(path=str(RESOURCE / "helpers.js"))
        invalid_page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))
        assert "invalid coalesced UTF-16 token ranges" in invalid_page.get_by_role("alert").inner_text()
        assert invalid_page.locator(".pb-date-query").count() == 0, "malformed token ranges must fail before rendering controls"
        invalid_page.close()
        browser.close()
    print("UI smoke passed: real mouse partial drag, touch-enabled Inspect, pinned snapshot, filtered inline history, UTC cutoff warning, build gating, and guest-token job flow")


if __name__ == "__main__":
    main()

"""Browser smoke test for the ResourceLoader UI with a contract-valid API stub."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "infra/wiki/extensions/PalimpsestBlame/resources"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame"></div></div></main>')
        page.evaluate(
            """() => {
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 0, wgArticleId: 42, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: (title, params) => '/wiki/' + title + '?' + new URLSearchParams(params) },
                    user: { tokens: { get: () => '+\\\\' } }
                };
                const revision = (id, parent, comment) => ({ revision_id: id, parent_id: parent, timestamp: '2026-03-15T10:00:00Z', user: 'Editor', comment, minor: false, source: null, url: '/wiki/Example?oldid=' + id, diff_url: '/w/index.php?diff=' + id + '&oldid=' + parent, contributions_url: '/wiki/Special:Contributions/Editor' });
                const base = {
                    status: 'ready', page: { id: 42, title: 'Example', language: 'en', latest_revision_id: 91 },
                    snapshot: { revision_id: 91, parent_id: 90, timestamp: '2026-03-15T10:00:00Z', user: 'Editor', comment: 'Changed phrase', url: '/wiki/Example?oldid=91', diff_url: '/w/index.php?diff=91&oldid=90', contributions_url: '/wiki/Special:Contributions/Editor' },
                    coverage: { history_complete: true, provenance_status: 'local', source_wiki: null, source_page_id: null, source_anchor_revision_id: null, source_anchor_timestamp: null, earliest_timestamp: '2026-02-01T00:00:00Z', latest_timestamp: '2026-03-15T10:00:00Z', reasons: [] },
                    source_text: 'alpha beta', html: '<p id="statement"><span data-pb-start="0" data-pb-end="5">alpha</span> <span data-pb-start="6" data-pb-end="10">beta</span></p>',
                    spans: [{ start: 0, end: 5, revision_id: 91, token_id: '91:0', lineage_ids: [], confidence: 'certain' }, { start: 6, end: 10, revision_id: 91, token_id: '91:1', lineage_ids: [], confidence: 'certain' }],
                    revisions: [revision(91, 90, 'Changed phrase'), revision(90, 89, 'Old text')],
                    events: [{ revision_id: 90, before: 'unrelated page edit', after: 'unrelated page edit', token_ids: ['90:0'], ambiguous: false }],
                    algorithm: { version: 'fixture-v1', semantics: 'last-change', limits: {} }, mapping: { mapped_characters: 9, unmapped_reasons: [] }
                };
                window.__requests = [];
                window.__forceUnavailable = false;
                window.__buildComplete = false;
                window.fetch = (input, init = {}) => {
                    const method = init.method || 'GET';
                    const url = new URL(String(input), location.href);
                    const params = new URLSearchParams(method === 'GET' ? url.search : init.body);
                    window.__requests.push({ method, params: Object.fromEntries(params.entries()) });
                    let response;
                    if (params.get('op') === 'build' && method === 'POST') {
                        window.__buildComplete = true;
                        response = { status: 'pending', job: { id: 'job-1', status: 'pending', processed: 0, total: 2 } };
                    } else if (params.get('op') === 'status') {
                        response = { status: 'ready', job: { id: params.get('jobid'), status: 'ready', processed: 2, total: 2 } };
                    } else if (params.get('op') === 'analyze' && window.__forceUnavailable && !window.__buildComplete) {
                        response = { status: 'unavailable', reason: 'Fixture requests a resumable build.' };
                    } else if (params.get('op') === 'versions') {
                        response = { status: 'ready', mode: params.get('mode'), bounds: { from: params.get('from'), to: params.get('to') }, versions: [{ revision_id: 90, timestamp: '2026-03-01T00:00:00Z', user: 'Editor' }], selected_revision_id: 90, continuation: null, coverage: base.coverage };
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
        assert page.locator("#mw-content-text > .mw-parser-output").count() == 1, "action-only page must receive a peer article container"
        assert "alpha beta" in page.locator(".mw-parser-output").inner_text()

        page.evaluate(
            """() => {
                const span = document.querySelector('[data-pb-start="0"]');
                const range = document.createRange();
                range.setStart(span.firstChild, 1);
                range.setEnd(span.firstChild, 4);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")
        assert page.locator(".pb-selected-text").inner_text() == "lph"
        assert page.locator(".pb-timeline").inner_text().find("unrelated page edit") == -1
        assert page.locator("#palimpsest-blame").evaluate("node => node.previousElementSibling.id") == "statement", "history panel must sit directly after the selected statement"
        sent_ranges = page.evaluate("window.__requests.filter(r => r.params.ranges).at(-1).params.ranges")
        assert sent_ranges == '[{"start":1,"end":4}]', sent_ranges

        page.get_by_role("button", name="Close history").click()
        page.get_by_role("textbox", name="Describe a date query").fill("Latest version before 1 April 2026")
        page.get_by_role("button", name="Interpret date query").click()
        assert "2026-04-01T00:00:00Z" in page.locator(".pb-date-preview").inner_text()
        page.get_by_role("button", name="Apply these bounds").click()
        page.wait_for_selector(".pb-version")
        versions_request = page.evaluate("window.__requests.filter(r => r.params.op === 'versions').at(-1)")
        assert versions_request["params"]["mode"] == "before"
        assert versions_request["params"]["to"] == "2026-04-01T00:00:00Z"

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
        page.get_by_role("button", name="Inspect selected article text").click()
        assert "no partial analysis was requested" in page.locator(".pb-warning").inner_text()
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').length") == analysis_count

        page.evaluate("window.__forceUnavailable = true")
        page.locator('[data-pb-start="0"]').click()
        page.get_by_role("button", name="Build full history").click()
        page.wait_for_selector(".pb-date-query")
        build_request = page.evaluate("window.__requests.filter(r => r.params.op === 'build').at(-1)")
        status_request = page.evaluate("window.__requests.filter(r => r.params.op === 'status').at(-1)")
        assert build_request["method"] == "POST"
        assert build_request["params"]["token"] == "+\\", "the valid anonymous CSRF token must reach POST unchanged"
        assert status_request["params"]["jobid"] == "job-1"
        assert page.evaluate("window.__requests.filter(r => r.params.op === 'analyze').at(-1).params.revision") == "91", "selection and retry analysis must stay pinned to the original snapshot"
        browser.close()
    print("UI smoke passed: action-only mount, pinned snapshot, exact selection, filtered timeline, inline placement, UTC version query, and guest-token bounded job flow")


if __name__ == "__main__":
    main()

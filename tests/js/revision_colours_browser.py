"""Computed-style and interaction regression for revision colour composition."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "infra/wiki/extensions/PalimpsestBlame/resources"


def fixture():
    words = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
    owners = [392, 392, 392, 393, 393, 393, 394, 394, 394, 394]
    source = " ".join(words)
    spans = []
    html_words = []
    cursor = 0
    owner_token_indexes = {392: 0, 393: 3, 394: 6}
    for word, owner in zip(words, owners):
        start = cursor
        end = start + len(word)
        token_id = f"{owner}:{owner_token_indexes[owner]}"
        owner_token_indexes[owner] += 1
        lineage = [token_id]
        if owner == 392 and word == "alpha":
            lineage.append("388:prior-alpha")
        spans.append({
            "start": start,
            "end": end,
            "revision_id": owner,
            "token_id": token_id,
            "token_ranges": [[start, end, token_id]],
            "lineage_ids": lineage,
            "confidence": "certain",
            "ambiguous": False,
        })
        html_words.append(f'<span data-pb-start="{start}" data-pb-end="{end}">{word}</span>')
        cursor = end + 1

    revisions = []
    for revision_id, parent, timestamp, user in [
        (388, 387, "2025-12-01T00:00:00Z", "Prior editor"),
        (390, 389, "2025-12-02T00:00:00Z", "Unrelated editor"),
        (392, 391, "2025-12-03T00:00:00Z", "Same editor"),
        (393, 392, "2025-12-04T00:00:00Z", "Same editor"),
        (394, 393, "2025-12-05T00:00:00Z", "Same editor"),
    ]:
        revisions.append({
            "revision_id": revision_id,
            "parent_id": parent,
            "timestamp": timestamp,
            "user": "Imported>SourceWiki" if revision_id == 394 else user,
            "comment": "Updated wording",
            "minor": False,
            "source": {"wiki": "enwiki", "page_id": 85, "revision_id": 393, "url": "/wiki/Example?oldid=393"} if revision_id == 394 else None,
            "url": f"/wiki/Example?oldid={revision_id}",
            "diff_url": f"/w/index.php?diff={revision_id}&oldid={parent}",
            "contributions_url": f"/wiki/Special:Contributions/{user.replace(' ', '_')}",
        })

    events = [
        {"revision_id": 392, "before": "prior alpha", "after": "alpha", "token_ids": ["392:0"], "ambiguous": False},
        {"revision_id": 393, "before": "prior delta", "after": "delta", "token_ids": ["393:3"], "ambiguous": False},
        {"revision_id": 394, "before": "prior eta", "after": "eta", "token_ids": ["394:6"], "ambiguous": False},
        {"revision_id": 388, "before": "older alpha", "after": "prior alpha", "token_ids": ["388:prior-alpha"], "ambiguous": False},
        {"revision_id": 389, "before": "deleted beside alpha", "after": "", "left_token_id": "392:0", "token_ids": [], "ambiguous": False},
        {"revision_id": 395, "before": "replaced beside alpha", "after": "replacement", "left_token_id": "392:0", "token_ids": [], "ambiguous": True},
        {"revision_id": 393, "before": "", "after": "inserted beside alpha", "left_token_id": "392:0", "token_ids": [], "ambiguous": False},
        {"revision_id": 390, "before": "unrelated", "after": "unrelated", "token_ids": ["390:unrelated"], "ambiguous": False},
    ]
    return {
        "status": "ready",
        "revision_id": 394,
        "page": {"id": 85, "title": "Example", "language": "en", "latest_revision_id": 394},
        "snapshot": {"revision_id": 394, "parent_id": 393, "timestamp": "2025-12-05T00:00:00Z", "user": "Same editor", "comment": "Updated wording", "url": "/wiki/Example?oldid=394", "diff_url": "/w/index.php?diff=394&oldid=393", "contributions_url": "/wiki/Special:Contributions/Same_editor"},
        "coverage": {"history_complete": True, "provenance_status": "verified", "reasons": []},
        "source_text": source,
        "html": '<p id="ten-words">' + " ".join(html_words) + "</p>",
        "spans": spans,
        "revisions": revisions,
        "events": events,
        "algorithm": {"version": "fixture-v1", "semantics": "last-change", "limits": {}},
        "mapping": {"mapped_characters": sum(map(len, words)), "unmapped_reasons": []},
    }


def contrast_report(page):
    return page.evaluate(
        """() => {
            const luminance = color => {
                const rgb = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => {
                    v /= 255;
                    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                });
                return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
            };
            const ratio = (fg, bg) => {
                const a = luminance(fg), b = luminance(bg);
                return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
            };
            const report = [];
            document.querySelectorAll('.pb-attributed[data-pb-color-index], .pb-selection-phrase[data-pb-color-index], .pb-revision-group[data-pb-color-index], .pb-event[data-pb-color-index]').forEach(node => {
                const style = getComputedStyle(node);
                report.push({ selector: node.className, fg: style.color, bg: style.backgroundColor, ratio: ratio(style.color, style.backgroundColor) });
                if (node.matches('.pb-event')) {
                    node.querySelectorAll('*').forEach(child => {
                        if (!child.textContent.trim()) return;
                        const childStyle = getComputedStyle(child);
                        report.push({ selector: child.tagName + '.' + child.className, text: child.textContent.trim(), fg: childStyle.color, bg: style.backgroundColor, ratio: ratio(childStyle.color, style.backgroundColor) });
                    });
                }
            });
            return report;
        }"""
    )


def owner_backgrounds(page):
    return page.evaluate(
        """() => Object.fromEntries(['392', '393', '394'].map(id => {
            const node = document.querySelector('.pb-attributed[data-pb-revision-id="' + id + '"]');
            return [id, getComputedStyle(node).backgroundColor];
        }))"""
    )


def main():
    data = fixture()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content('<main><div id="mw-content-text"><div id="palimpsest-blame" data-revision="394"></div></div></main>')
        page.add_style_tag(path=str(RESOURCE / "ext.palimpsestBlame.css"))
        page.evaluate(
            """fixture => {
                window.__fixture = fixture;
                window.__requests = [];
                window.__paletteValues = new Map();
                Object.defineProperty(window, 'sessionStorage', { configurable: true, value: {
                    getItem: key => window.__paletteValues.has(key) ? window.__paletteValues.get(key) : null,
                    setItem: (key, value) => window.__paletteValues.set(key, value)
                } });
                window.mw = {
                    config: { get: () => ({ wgPageName: 'Example', wgRevisionId: 0, wgArticleId: 85, wgCanonicalSpecialPageName: null }) },
                    util: { wikiScript: () => 'https://example.test/api.php', getUrl: (title, params) => '/wiki/' + title + '?' + new URLSearchParams(params) },
                    user: { tokens: { get: () => '+\\\\' } }
                };
                window.fetch = input => {
                    const params = new URLSearchParams(new URL(String(input), location.href).search);
                    window.__requests.push(Object.fromEntries(params.entries()));
                    let response = window.__fixture;
                    if (params.get('op') === 'analyze' && params.get('ranges')) {
                        response = Object.assign({}, response, { selection: {
                            ranges: JSON.parse(params.get('ranges')),
                            revision_ids: Array.from(new Set(response.spans.map(span => span.revision_id))),
                            events: response.events.filter(event => event.revision_id !== 390),
                            ambiguous: false,
                            reasons: []
                        } });
                    } else if (params.get('op') === 'versions') {
                        response = { status: 'ready', mode: params.get('mode'), bounds: { from: params.get('from'), to: params.get('to') }, versions: [{ revision_id: 394, timestamp: '2025-12-05T00:00:00Z', user: 'Same editor' }], selected_revision_id: 394, continuation: null, coverage: window.__fixture.coverage };
                    }
                    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ palimpsestblame: response }) });
                };
            }""",
            data,
        )
        page.add_script_tag(path=str(RESOURCE / "helpers.js"))
        page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))
        page.wait_for_selector(".pb-date-query")

        page.evaluate(
            """() => {
                const words = document.querySelectorAll('[data-pb-start]');
                const selection = window.getSelection();
                selection.setBaseAndExtent(words[0].firstChild, 0, words[9].firstChild, words[9].textContent.length);
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")

        sentence = data["source_text"]
        assert page.locator(".pb-selected-text").text_content() == sentence
        assert page.locator(".pb-selection-phrase").count() == 10
        groups = page.locator(".pb-revision-group")
        assert groups.count() == 3
        assert page.locator(".pb-revision-group-focus").evaluate_all("nodes => nodes.every(node => node.getAttribute('aria-pressed') === 'false')")
        assert page.locator(".pb-selection-phrase").evaluate_all("nodes => nodes.every(node => node.getAttribute('aria-pressed') === 'false')")
        expected_snippets = {
            "392": ["alpha beta gamma"],
            "393": ["delta epsilon zeta"],
            "394": ["eta theta iota kappa"],
        }
        for revision_id, snippets in expected_snippets.items():
            group = page.locator(f'.pb-revision-group[data-pb-revision-id="{revision_id}"]')
            assert group.locator(".pb-group-snippet").all_text_contents() == snippets
        imported_group_text = page.locator('.pb-revision-group[data-pb-revision-id="394"]').inner_text()
        assert "Imported from enwiki (source page 85, source revision 393; local revision 394)" in imported_group_text
        assert "mapped provenance, not independent authentication" in imported_group_text
        assert "Imported from" not in page.locator('.pb-revision-group[data-pb-revision-id="392"]').inner_text()

        owner_ids = page.locator(".pb-selection-phrase").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)")
        assert owner_ids == ["392"] * 3 + ["393"] * 3 + ["394"] * 4
        article_ids = page.locator(".pb-attributed").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)")
        assert article_ids == owner_ids

        light_backgrounds = owner_backgrounds(page)
        assert len(set(light_backgrounds.values())) == 3, light_backgrounds
        def rgb(value):
            return tuple(map(int, value.removeprefix("rgb(").removesuffix(")").split(", ")))
        light_colors = list(light_backgrounds.values())
        assert min(sum((a - b) ** 2 for a, b in zip(rgb(left), rgb(right))) ** 0.5 for i, left in enumerate(light_colors) for right in light_colors[i + 1:]) >= 48, light_backgrounds
        mapped_bg_by_owner = page.locator(".pb-attributed").evaluate_all("nodes => nodes.map(node => [node.dataset.pbRevisionId, getComputedStyle(node).backgroundColor])")
        phrase_bg_by_owner = page.locator(".pb-selection-phrase").evaluate_all("nodes => nodes.map(node => [node.dataset.pbRevisionId, getComputedStyle(node).backgroundColor])")
        for revision_id, background in mapped_bg_by_owner:
            assert background == light_backgrounds[revision_id]
        for revision_id, background in phrase_bg_by_owner:
            assert background == light_backgrounds[revision_id]
        group_bg = page.locator(".pb-revision-group").evaluate_all("nodes => Object.fromEntries(nodes.map(node => [node.dataset.pbRevisionId, getComputedStyle(node).backgroundColor]))")
        assert group_bg == light_backgrounds
        event_bg = page.locator('.pb-event[data-pb-revision-id="392"]').evaluate("node => getComputedStyle(node).backgroundColor")
        assert event_bg == light_backgrounds["392"]

        for contrast in contrast_report(page):
            assert contrast["ratio"] >= 4.5, contrast

        request_count = page.evaluate("window.__requests.filter(request => request.op === 'analyze').length")
        first_phrase = page.locator('.pb-selection-phrase[data-pb-revision-id="392"]').first
        first_phrase.click()
        assert page.locator('.pb-revision-group[data-pb-revision-id="392"].is-focused').count() == 1
        assert page.locator(".pb-selection-phrase.is-focused").count() == 1
        assert first_phrase.get_attribute("aria-pressed") == "true"
        assert page.locator('.pb-selection-phrase[data-pb-revision-id="392"]').nth(1).get_attribute("aria-pressed") == "false"
        assert page.locator(".pb-selected-text").text_content() == sentence
        focused_ids = page.locator(".pb-event").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)")
        assert set(focused_ids) == {"392", "388", "389", "395"}, focused_ids
        assert "390" not in focused_ids and "393" not in focused_ids and "394" not in focused_ids
        assert page.locator(".pb-event").evaluate_all("nodes => nodes.map(node => [node.dataset.pbRevisionId, getComputedStyle(node).backgroundColor])").pop()[1] != "", "history events must use revision colours"
        page.get_by_role("button", name="Show full selection").click()
        full_event_ids = page.locator(".pb-event").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)")
        assert set(full_event_ids) == {"392", "393", "394", "388", "389", "395"}, full_event_ids
        assert "390" not in full_event_ids, "the full selected-wording history must remain scoped to selected lineage"

        group_trigger = page.locator('.pb-revision-group[data-pb-revision-id="393"] .pb-revision-group-focus')
        group_trigger.focus()
        page.keyboard.press("Enter")
        assert page.locator('.pb-revision-group[data-pb-revision-id="393"].is-focused').count() == 1
        assert group_trigger.get_attribute("aria-pressed") == "true"
        assert page.locator('.pb-revision-group[data-pb-revision-id="392"] .pb-revision-group-focus').get_attribute("aria-pressed") == "false"
        assert page.locator('.pb-selection-phrase[data-pb-revision-id="393"]').evaluate_all("nodes => nodes.every(node => node.getAttribute('aria-pressed') === 'true')")
        assert page.locator(".pb-event").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)") == ["393"]
        page.get_by_role("button", name="Show full selection").click()
        assert page.locator(".pb-revision-group-focus").evaluate_all("nodes => nodes.every(node => node.getAttribute('aria-pressed') === 'false')")
        assert page.locator(".pb-selection-phrase").evaluate_all("nodes => nodes.every(node => node.getAttribute('aria-pressed') === 'false')")
        assert page.evaluate("window.__requests.filter(request => request.op === 'analyze').length") == request_count, "quote and group focus are local interactions"

        page.evaluate("document.documentElement.classList.add('skin-theme-clientpref-night')")
        dark_backgrounds = owner_backgrounds(page)
        assert len(set(dark_backgrounds.values())) == 3, dark_backgrounds
        assert dark_backgrounds != light_backgrounds
        dark_colors = list(dark_backgrounds.values())
        assert min(sum((a - b) ** 2 for a, b in zip(rgb(left), rgb(right))) ** 0.5 for i, left in enumerate(dark_colors) for right in dark_colors[i + 1:]) >= 48, dark_backgrounds
        for contrast in contrast_report(page):
            assert contrast["ratio"] >= 4.5, contrast

        page.evaluate("document.documentElement.classList.remove('skin-theme-clientpref-night'); document.documentElement.classList.add('skin-theme-clientpref-os')")
        page.emulate_media(color_scheme="dark")
        assert owner_backgrounds(page) == dark_backgrounds, "Vector OS preference must use dark revision fills when the OS requests dark mode"
        for contrast in contrast_report(page):
            assert contrast["ratio"] >= 4.5, contrast
        page.emulate_media(color_scheme="light")
        assert owner_backgrounds(page) == light_backgrounds, "Vector OS preference must use light revision fills when the OS requests light mode"

        page.evaluate("document.documentElement.classList.remove('skin-theme-clientpref-os'); document.documentElement.classList.add('skin-theme-clientpref-day')")
        page.get_by_role("textbox", name="Describe a date query").fill("Latest version before 1 April 2026")
        page.get_by_role("button", name="Interpret date query").click()
        page.get_by_role("button", name="Apply these bounds").click()
        page.wait_for_selector(".pb-version")
        assert owner_backgrounds(page) == light_backgrounds, "date navigation must not reassign loaded revision colours"
        assert page.locator(".pb-selected-text").text_content() == sentence
        assert "Colours can repeat in long histories" in page.locator(".pb-legend").inner_text()
        assert "Color category" not in page.locator(".pb-legend").inner_text()
        assert "mapped passage" not in page.locator(".pb-legend").inner_text()

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "the coloured selection view must not overflow the mobile viewport"

        stable_revision_393 = light_backgrounds["393"]
        page.get_by_role("button", name="Close history").click()
        page.evaluate(
            """() => {
                const alpha = window.__fixture.spans.find(span => span.start === 0);
                alpha.revision_id = 391;
                alpha.token_id = '391:0';
                alpha.token_ranges = alpha.token_ranges.map(range => [range[0], range[1], '391:0']);
                alpha.lineage_ids = alpha.lineage_ids.map(id => id === '392:0' ? '391:0' : id);
                const revision = Object.assign({}, window.__fixture.revisions.find(item => item.revision_id === 392), { revision_id: 391, parent_id: 390 });
                window.__fixture.revisions.push(revision);
                const words = document.querySelectorAll('[data-pb-start]');
                const selection = window.getSelection();
                selection.setBaseAndExtent(words[0].firstChild, 0, words[9].firstChild, words[9].textContent.length);
            }"""
        )
        page.get_by_role("button", name="Inspect selected article text").click()
        page.wait_for_selector(".pb-breakdown")
        changed_prefix_group = page.locator('.pb-revision-group[data-pb-revision-id="393"]')
        assert changed_prefix_group.evaluate("node => getComputedStyle(node).backgroundColor") == stable_revision_393, "a later snapshot with a new earlier owner must preserve the page-level color assigned to revision 393"
        page.evaluate(
            """() => {
                const replacement = document.createElement('div');
                replacement.id = 'palimpsest-blame';
                replacement.dataset.revision = '394';
                document.getElementById('palimpsest-blame').replaceWith(replacement);
            }"""
        )
        page.add_script_tag(path=str(RESOURCE / "ext.palimpsestBlame.js"))
        page.wait_for_function("document.querySelector('.pb-attributed[data-pb-revision-id=\"393\"]')")
        restored_group = page.locator('.pb-attributed[data-pb-revision-id="393"]').first
        assert restored_group.evaluate("node => getComputedStyle(node).backgroundColor") == stable_revision_393, "the page-scoped session registry must preserve colors when the page script initializes again"
        browser.close()
    print("revision colour smoke passed: 3/3/4 owners, exact quote/groups, lineage focus, Vector themes, contrast, date stability, and mobile width")


if __name__ == "__main__":
    main()

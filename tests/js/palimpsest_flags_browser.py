"""Fixture browser acceptance for PalimpsestFlags; run in the pinned browser image."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "infra/wiki/extensions/PalimpsestFlags/resources"


def flags():
    return [{"id": "u0-s1", "kind": "FACT", "tier": "admin", "title": "Number changed", "reason": "Evidence disagrees.", "confidence": .85, "side": "new", "anchor_text": "1,200", "anchor_start": None, "anchor_end": None, "context_sentence": "The number is 1,200.", "evidence": [{"source": "cited", "quote": "900", "url": "https://example.org/a"}], "citations": ["https://example.org/a"], "neutral_rewrite": "The source gives 900.", "check": "judge"}, {"id": "u0-s2", "kind": "MOTIVE", "tier": "review", "title": "Loaded motive", "reason": "Needs attribution.", "confidence": .6, "side": "old", "anchor_text": "900", "anchor_start": None, "anchor_end": None, "context_sentence": "The number was 900.", "evidence": [], "citations": [], "neutral_rewrite": None, "check": "judge"}, {"id": "u0-s3", "kind": "FRAMING", "tier": "review", "title": "Third card", "reason": "Nearby finding.", "confidence": .6, "side": "new", "anchor_text": "number", "anchor_start": None, "anchor_end": None, "context_sentence": "The number is 1,200.", "evidence": [], "citations": [], "neutral_rewrite": None, "check": "judge"}, {"id": "u0-s4", "kind": "CITED_PAGE", "tier": "review", "title": "No anchor", "reason": "Fallback.", "confidence": .5, "side": "new", "anchor_text": "NONEXISTENT", "anchor_start": None, "anchor_end": None, "context_sentence": "Visible fallback context.", "evidence": [], "citations": [], "neutral_rewrite": None, "check": "render"}]


def install(page, response):
    page.set_content('''<style>.pf-card{height:80px}.pf-rail__item{position:absolute}.pf-workspace{display:grid;grid-template-columns:1fr 288px}.pf-popover{position:fixed}</style><table class="diff"><tr><td class="diff-deletedline">The number was <del class="diffchange">900</del>.</td><td class="diff-addedline">The <ins class="diffchange">number is 1,</ins>200.</td></tr></table>''')
    page.evaluate("""response => {
        window.mw = { config: { get: key => key === 'wgPalimpsestFlags' ? { oldid: 10, diff: 11, title: 'Example', language: 'en' } : (key === 'wgDiffOldId' ? 10 : key === 'wgDiffNewId' ? 11 : null) }, util: { wikiScript: () => '/api.php' }, hook: () => ({ add: () => {} }) };
        window.fetch = () => response;
    }""", response)
    page.add_script_tag(path=str(RESOURCE / "anchoring.js")); page.add_script_tag(path=str(RESOURCE / "stacking.js")); page.add_script_tag(path=str(RESOURCE / "ext.palimpsest.flags.js"))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        payload = json.dumps(flags())
        install(page, page.evaluate_handle("""() => new Promise(resolve => { window.__resolveFlags = () => resolve({ ok: true, json: () => Promise.resolve({ palimpsestflags: { status: 'ok', flags: %s, partial: false } }) }); })""" % payload))
        page.wait_for_selector(".pf-summary-bar .cdx-progress-indicator")
        assert page.locator("table.diff").is_visible(), "diff must be visible while request is pending"
        page.evaluate("__resolveFlags()")
        page.wait_for_selector("mark.pf-anchor[data-pf-id='u0-s1']")
        assert page.locator("table.diff").inner_text() == "The number was 900.The number is 1,200."
        assert page.locator("mark[data-pf-id='u0-s1']").count() == 2, "span crossing ins/plain text wraps both text nodes"
        assert page.locator("mark[data-pf-id='u0-s2']").inner_text() == "900"
        assert "Visible fallback context." in page.locator(".pf-unanchored-tray").inner_text()

        # Inline mode must not let old/new text matches cross ins/del boundaries.
        inline = page.evaluate("""() => {
            const table = document.createElement('table'); table.className = 'diff mw-diff-inline';
            table.innerHTML = '<tr><td class="mw-diff-inline-changed"><del>900</del><ins>1,200</ins></td></tr>';
            document.body.append(table);
            const f = id => ({ id, kind: 'FACT', tier: 'admin', side: id === 'old' ? 'old' : 'new', anchor_text: id === 'old' ? '900' : '1,200', context_sentence: '', anchor_start: null });
            const result = window.PalimpsestFlagsAnchoring.resolve(table, [f('old'), f('new')]);
            return result.anchored.map(x => [x.flag.id, x.mark.textContent]);
        }""")
        assert inline == [["old", "900"], ["new", "1,200"]]
        page.locator(".pf-card[data-pf-id='u0-s3'] .pf-card__toggle").click()
        page.wait_for_timeout(20)
        assert page.locator(".pf-card[data-pf-id='u0-s3']").count() == 1
        geometry = page.locator(".pf-rail__item").evaluate_all("nodes => nodes.map(n => { const r = n.getBoundingClientRect(); return [r.top, r.bottom]; })")
        assert all(geometry[i][0] - geometry[i - 1][1] >= 8 for i in range(1, len(geometry)))
        page.keyboard.press("]"); page.keyboard.press("x")
        assert page.locator(".pf-reviewed[aria-pressed='true']").count() >= 1
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 900, "height": 900}); page.wait_for_timeout(30)
        assert page.locator(".pf-inline-pin").count() > 0
        page.locator(".pf-inline-pin").first.click(); page.wait_for_selector(".cdx-popover")
        # Browser-side WCAG calculation covers every approved light/dark solid chip pair.
        assert page.evaluate("""() => { const p=[['b32424','ffffff'],['6b4ba1','ffffff'],['f0b400','101418'],['b95000','ffffff'],['101418','ffffff'],['3366cc','ffffff'],['0e7369','ffffff'],['fd7865','101418'],['bba2e5','101418'],['eeb533','101418'],['ff9e5e','101418'],['080a0c','f8f9fa'],['88a3e8','101418'],['59d1c5','101418']]; const l=h=>{const a=h.match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*a[0]+.7152*a[1]+.0722*a[2]}; return p.every(([a,b])=> (Math.max(l(a),l(b))+.05)/(Math.min(l(a),l(b))+.05)>=4.5); }""")
        browser.close()
    print("PalimpsestFlags fixture acceptance passed")


if __name__ == "__main__":
    main()

'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname, 'static/lab-explorer.js'), 'utf8');
const start = code.indexOf(' function renderEvidence('), end = code.indexOf(' function reviewKey(', start);
assert.ok(start >= 0 && end > start);

function fixture(cached) {
    const nodes = [], calls = [];
    function el(tag, className = '', textContent = '') {
        const node = { tag, className, textContent, children: [],
            append(...items) { this.children.push(...items); },
            replaceChildren(...items) { this.children = items; },
            setAttribute() {}, insertBefore(item) { this.children.unshift(item); } };
        nodes.push(node);
        return node;
    }
    const content = el('section');
    const state = { current: 'en', evidenceRequest: 1 };
    const context = { URL, state, names: { en: 'English', sv: 'Swedish' },
        labels: { coverage: 'Additional context' },
        $: () => content, el, icon: () => el('svg'), fmt: value => value,
        document: { querySelector: () => ({ content: 'fixture-token' }) },
        json: async (...args) => { calls.push(args); return { text: 'Explicit local translation' }; } };
    vm.createContext(context);
    vm.runInContext(code.slice(start, end), context);
    const data = { title: 'Fixture', kind: 'coverage', label: 'Additional context', occurrences: 1,
        evidence: [
            { lang: 'en', revision: 1, stamp: '2025-01-01', quote: 'English evidence', quote_html: 'English evidence', url: 'https://en.wikipedia.org/w/index.php?oldid=1' },
            { lang: 'sv', revision: 2, stamp: '2025-01-01', quote: 'Svensk evidens', quote_html: 'Svensk evidens', translation: cached ? 'Saved translation' : '', url: 'https://sv.wikipedia.org/w/index.php?oldid=2' }
        ] };
    context.renderEvidence(data, 1);
    return { calls, button: nodes.find(node => node.className === 'translation-button'), nodes };
}

(async () => {
    const fresh = fixture(false);
    assert.equal(fresh.calls.length, 0, 'Opening uncached evidence must not start translation');
    assert.equal(fresh.button.textContent, 'Translate locally');
    await fresh.button.onclick();
    assert.equal(fresh.calls.length, 1, 'Only the explicit button starts translation');
    assert.equal(fresh.calls[0][0], '/translations');
    assert.equal(fresh.calls[0][1].method, 'POST');
    assert.equal(JSON.parse(fresh.calls[0][1].body).text, 'Svensk evidens');
    fresh.button.onclick();
    assert.equal(fresh.calls.length, 1, 'Hiding a translation must not generate another');
    const cached = fixture(true);
    assert.equal(cached.calls.length, 0);
    assert.equal(cached.button.textContent, 'Hide translation');
    cached.button.onclick();
    assert.equal(cached.calls.length, 0, 'Cached translations remain read-only');
    console.log('Explicit local translation and cached-read controls passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

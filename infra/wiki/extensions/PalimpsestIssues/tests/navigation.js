/* Execute the actual native entrypoint with a minimal DOM/API test harness. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../resources/issues.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function page(query, selected = '20') {
    const calls = [], listeners = {}, article = {}, sources = {};
    const root = { innerHTML: '', querySelector: () => ({ append() {} }) };
    const select = { value: selected, addEventListener: (type, fn) => { listeners[type] = fn; } };
    const config = { title: 'Article', edition: 'en', query, articleUrl: '/index.php/Article', canScan: false };
    const context = {
        URL, URLSearchParams, console,
        location: { origin: 'http://wiki.test' },
        history: { replaceState() { throw Error('Unexpected historical fallback'); } },
        document: {
            getElementById: id => ({ 'palimpsest-issues': root, 'flags-revision': select, 'native-scan-sources': sources })[id],
            querySelector: selector => selector === '#ca-view a' ? article : null,
            createElement: () => ({})
        },
        mw: {
            config: { get: () => config },
            Api: class {
                async get(params) {
                    calls.push(params.op);
                    if (params.op === 'versions') return { palimpsestissues: { versions: [ { source: 10 }, { source: 20 } ] } };
                    if (params.op === 'cached') return { palimpsestissues: { status: 'ok', flags: [] } };
                    throw Error('Unexpected API operation: ' + params.op);
                }
                postWithToken() { throw Error('Navigation must never mutate or scan'); }
            },
            loader: { using: async () => {} }
        },
        window: {}
    };
    vm.runInNewContext(source, context);
    await settle();
    return { calls, root, article, sources, select, listeners };
}

(async () => {
    const absent = await page({ checks: '1', revision: '999', run: 'original', group: 'group', stamp: 'checkpoint' });
    assert.deepEqual(absent.calls, ['versions']);
    assert.match(absent.root.innerHTML, /Source revision 999 is not imported/);
    assert.doesNotMatch(absent.root.innerHTML, /id="flags-revision"/);
    const hrefs = [...absent.root.innerHTML.matchAll(/href="([^"]+)"/g)].map(match => new URL(match[1].replaceAll('&amp;', '&')));
    assert.equal(hrefs[0].searchParams.get('run'), 'original');
    for (const key of ['issue', 'observation', 'occurrence', 'group', 'stamp', 'checks']) assert.equal(hrefs[0].searchParams.has(key), false);
    assert.equal(hrefs[1].searchParams.has('revision'), false);
    assert.equal(hrefs[1].searchParams.get('checks'), '1');

    const local = await page({ checks: '1', local_revision: '999' });
    assert.deepEqual(local.calls, ['versions']);
    assert.match(local.root.innerHTML, /Local revision 999 has no verified source mapping/);
    assert.doesNotMatch(local.root.innerHTML, /id="flags-revision"/);

    const valid = await page({ checks: '1', revision: '20', oldid: '300', issue: 'stale-observation' });
    assert.deepEqual(valid.calls, ['versions', 'cached']);
    for (const revision of ['20', '10']) {
        valid.select.value = revision;
        valid.listeners.change();
        const link = new URL(valid.article.href);
        assert.equal(link.searchParams.get('source'), revision);
        assert.equal(link.searchParams.get('revision'), revision);
        for (const key of ['oldid', 'checks', 'issue', 'observation', 'occurrence']) assert.equal(link.searchParams.has(key), false);
        assert.match(valid.sources.innerHTML, new RegExp('oldid=' + revision));
    }
    assert.deepEqual(valid.calls, ['versions', 'cached']);
    console.log('Native missing-revision, selection, article-link and return navigation checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

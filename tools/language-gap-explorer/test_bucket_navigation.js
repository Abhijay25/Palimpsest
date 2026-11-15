'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'static/lab-explorer.js'), 'utf8');
function functionBlock(start, end) {
    const a = source.indexOf(start), b = source.indexOf(end, a);
    assert.ok(a >= 0 && b > a);
    return source.slice(a, b);
}
const queryCode = functionBlock(' function context()', ' function save()');
const bucketCode = functionBlock(' function openBucket(', ' function resetOverview(');
const restoreCode = functionBlock(' function configureViewBounds(', ' function closeEvidence(');
const date = value => Date.parse(value + 'T00:00:00Z');

function fixture(native = true, scale = 'month', categories = ['coverage', 'FRAMING']) {
    const state = { topic: 'Q134949', languages: ['en', 'fi', 'sv'], current: 'en', run: 'original-run',
        data: {}, matrix: { native_issues_url: native ? 'http://localhost:18093/index.php?title=Winter_War&action=issues' : null },
        level: 'overview', from: date('2025-01-01'), to: date('2025-07-30'),
        overviewFrom: date('2025-01-01'), overviewTo: date('2025-07-30'),
        scale, categories, pair: 'FI–SV', q: 'volunteers', mode: 'keyword' };
    const before = JSON.stringify(state), assigned = [], rewritten = [], effects = [];
    const scroll = { scrollTop: 200 };
    const context = { state, URL, URLSearchParams,
        bounds: () => [date('2020-01-01'), date('2025-07-30')],
        location: { assign: url => assigned.push(url) },
        history: { replaceState: (...args) => rewritten.push(args) },
        closeEvidence: () => effects.push('closeEvidence'), render: () => effects.push('render'),
        search: () => effects.push('search'), $: () => scroll };
    vm.createContext(context);
    vm.runInContext(queryCode + bucketCode + restoreCode, context);
    return { state, before, assigned, rewritten, effects, scroll, open: context.openBucket, restore: context.configureViewBounds };
}

for (const scale of ['month', 'year']) {
    const f = fixture(true, scale);
    f.open({ start: date(scale === 'month' ? '2025-07-01' : '2025-01-01'), end: date(scale === 'month' ? '2025-08-01' : '2026-01-01') });
    assert.equal(JSON.stringify(f.state), f.before, 'Bar handoff must not turn the origin histogram into a list');
    assert.deepEqual(f.effects, [], 'No internal issue-list render or search before navigation');
    assert.deepEqual(f.rewritten, [], 'Browser Back must keep the original histogram history entry');
    assert.equal(f.assigned.length, 1);
    const target = new URL(f.assigned[0]), q = target.searchParams;
    assert.equal(target.pathname, '/index.php');
    assert.equal(q.get('action'), 'issues');
    assert.equal(q.get('view'), 'history');
    assert.equal(q.get('run'), 'original-run');
    assert.equal(q.get('from'), scale === 'month' ? '2025-07-01' : '2025-01-01');
    assert.equal(q.get('to'), '2025-07-29');
    assert.deepEqual(q.getAll('languages[]'), ['en', 'fi', 'sv']);
    assert.deepEqual(q.getAll('kinds[]'), ['coverage', 'FRAMING']);
    const back = new URLSearchParams(q.get('skyline'));
    assert.equal(back.get('view'), 'overview', 'The article return link must also restore the histogram');
    assert.equal(back.get('from'), '2025-01-01T00:00:00.000Z');
    assert.equal(back.get('to'), '2025-07-30T00:00:00.000Z');
    assert.equal(back.get('pair'), 'FI–SV');
    assert.equal(back.get('categories'), 'coverage,FRAMING');
    assert.equal(back.get('q'), 'volunteers');
    assert.equal(back.get('issue_return'), '1');
}
const empty = fixture(true, 'month', []);
empty.open({ start: date('2025-07-01'), end: date('2025-08-01') });
assert.equal(new URL(empty.assigned[0]).searchParams.get('kind'), 'NONE_SELECTED');
const standalone = fixture(false);
standalone.open({ start: date('2025-07-01'), end: date('2025-08-01') });
assert.equal(standalone.state.level, 'questions', 'Unconfigured standalone preview remains usable');
assert.deepEqual(standalone.effects, ['closeEvidence', 'render', 'search']);
assert.equal(standalone.assigned.length, 0);
const legacy = fixture();
legacy.state.level = 'questions';
legacy.state.from = date('2025-07-01');
legacy.state.period = '2025-07';
legacy.restore(true);
assert.equal(legacy.state.level, 'overview', 'Old bucket-list history entries must restore the histogram too');
assert.equal(legacy.state.from, date('2025-01-01'));
assert.equal(legacy.state.to, date('2025-07-30'));
const exact = fixture();
exact.state.level = 'questions';
exact.state.selected = 'exact-original-finding';
exact.state.period = '2025-07';
exact.restore(true);
assert.equal(exact.state.level, 'questions', 'Existing exact finding/evidence links retain their identity');
assert.equal(exact.state.from, date('2025-07-01'));
console.log('Native bucket handoff preserves histogram history, return state and exact month/year filters.');

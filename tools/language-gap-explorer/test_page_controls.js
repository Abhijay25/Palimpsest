'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, 'static/flags/flags.js'), 'utf8');
const start = source.indexOf(' function pageCard('), end = source.indexOf(' function highlightPageSentence(', start);
assert.ok(start >= 0 && end > start);
const calls = [], status = { textContent: '' }, events = {}, attributes = {};
const card = { className: '', tabIndex: -1, innerHTML: '',
    setAttribute(key, value) { attributes[key] = value; },
    querySelector(selector) { assert.equal(selector, '.page-anchor-status'); return status; },
    addEventListener(name, handler) { events[name] = handler; } };
let found = true;
const context = { document: { createElement: () => card }, labels: { FACT: 'Fact' },
    esc: value => String(value).replaceAll('<', '&lt;'),
    highlightPageSentence: quote => { calls.push(quote); return found; } };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.pageCard({ kind: 'FACT', title: 'Test annotation', reason: '<quoted reason>', context_sentence: 'Exact quote' });
assert.ok(card.className.includes('is-open'), 'Page explanations must be visible under shared collapsed-card CSS');
assert.ok(card.innerHTML.includes('&lt;quoted reason>'));
assert.equal(attributes.role, 'button');
assert.equal(calls.length, 0, 'Rendering must not pretend an anchor has already been found');
events.click();
assert.equal(calls[0], 'Exact quote');
assert.equal(status.textContent, 'Passage highlighted in the article below.');
found = false;
let prevented = false;
events.keydown({ key: 'Enter', preventDefault() { prevented = true; } });
assert.equal(prevented, true);
assert.ok(status.textContent.includes('could not be anchored'));
assert.equal(calls.length, 2);
console.log('Page explanations, keyboard activation and honest absent-anchor feedback passed.');

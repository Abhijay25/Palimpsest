/* Optional revision-audit tab; mirrors the native Palimpsest Flags reading order. */
/* Standalone port of ext.palimpsest.flags.js: no mw APIs, same audit interaction. */
(function () {
  'use strict';
  var $ = function (selector) { return document.querySelector(selector); };
  var labels = { FACT: 'Fact', MOTIVE: 'Motive', FRAMING: 'Wording', REMOVED_CONTEXT: 'Removed context', HIDDEN_TEXT: 'Hidden text', CITATION_DATE: 'Citation date', CITED_PAGE: 'Cited page', CHERRY_PICK: 'Selective quote', OUT_OF_SYNC: 'Out of sync' };
  var icons = { FACT: '⚠', MOTIVE: '◉', FRAMING: '❝', REMOVED_CONTEXT: '−', HIDDEN_TEXT: '◌', CITATION_DATE: '◷', CITED_PAGE: '⌁', CHERRY_PICK: '❝', OUT_OF_SYNC: '↔' };
  var root = $('#flags-audit'), table, auditFlags = [], pageFlags = [], rail;
  if (!root || !window.PalimpsestRail || !window.PalimpsestFlagsAnchoring) return;
  function esc(value) { return String(value || '').replace(/[&<>"']/g, function (character) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]; }); }
  function safeUrl(value) { try { var url = new URL(value, location.href); return /^https?:$/.test(url.protocol) ? url.href : ''; } catch (_) { return ''; } }
  function el(tag, cls, text) { var node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
  function action(cls, text) { var node = el('button', cls, text); node.type = 'button'; return node; }
  function current() { var select = $('#flags-revision'); return { topic: root.dataset.topic, lang: select && select.selectedOptions[0] ? select.selectedOptions[0].dataset.lang : root.dataset.lang, revision: Number(select && select.value) }; }
  function auditUrl(path) { var url = new URL(path, location.origin), source = new URL(location); ['run', 'group', 'stamp', 'occurrence', 'fresh'].forEach(function (key) { if (source.searchParams.has(key)) url.searchParams.set(key, source.searchParams.get(key)); }); return url.pathname + url.search; }
  function sourceName(source) { return ({ cited: 'Cited source', old: 'Prior revision', new: 'Selected revision', page: 'Elsewhere on this page' })[source] || 'Evidence'; }
  function reviewKey(flag) { var row = current(); return 'palimpsest-flags-reviewed-' + row.topic + '-' + row.lang + '-' + row.revision + '-' + flag.id; }
  function reviewed(flag) { try { return localStorage.getItem(reviewKey(flag)) === 'reviewed'; } catch (_) { return false; } }
  function setReviewed(flag, value) { try { localStorage.setItem(reviewKey(flag), value ? 'reviewed' : 'pending'); } catch (_) {} }
  function appendEvidence(body, flag) {
    (flag.evidence || []).filter(function (item) { return String(item.quote || '').trim(); }).forEach(function (item) {
      var wrap = el('section', 'flag-card__evidence-wrap'), quote = el('blockquote', 'flag-card__evidence', item.quote), meta = el('div', 'flag-card__evidence-meta'), href = safeUrl(item.url);
      if (href) { var link = el('a', '', sourceName(item.source)); link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; meta.appendChild(link); } else meta.appendChild(el('span', '', sourceName(item.source)));
      if (item.section) meta.appendChild(el('span', 'flag-card__section', item.section)); wrap.append(quote, meta); body.appendChild(wrap);
    });
  }
  function cardFor(item, expanded, select) {
    var flag = item.flag, isReviewed = reviewed(flag), kind = String(flag.kind || 'OUT_OF_SYNC').toLowerCase();
    var card = el('article', 'flag-card flag-card--' + kind + ' flag-card--' + (flag.tier || 'review') + (isReviewed ? ' flag-card--reviewed' : ''));
    card.tabIndex = 0; card.setAttribute('role', 'button'); card.setAttribute('aria-label', (labels[flag.kind] || flag.kind) + ': ' + (flag.title || 'Flag'));
    var head = el('div', 'flag-card__meta'), pill = el('span', 'flag-card__pill flag-card__pill--' + (flag.tier || 'review'));
    pill.append(el('span', 'flag-card__icon', icons[flag.kind] || '•'), document.createTextNode(' ' + (labels[flag.kind] || flag.kind || 'Out of sync')));
    head.append(pill, el('strong', 'flag-card__tier', flag.tier === 'admin' ? 'Admin' : 'Review'));
    if (flag.side === 'old') head.appendChild(el('span', 'flag-card__old', '← OLD'));
    var review = action('flag-card__review', isReviewed ? 'Reviewed' : 'Mark reviewed'); review.setAttribute('aria-pressed', String(isReviewed));
    review.addEventListener('click', function (event) { event.stopPropagation(); setReviewed(flag, !isReviewed); rail.render(); }); head.appendChild(review);
    card.appendChild(head);
    if (expanded && !isReviewed) {
      var body = el('div', 'flag-card__body');
      var anchored = flag.anchor_text || flag.context_sentence || flag.related_anchor_text;
      if (anchored) card.appendChild(el('blockquote', 'flag-card__quote', anchored));
      card.appendChild(el('div', 'flag-card__title', flag.title || labels[flag.kind] || 'Flag'));
      if (flag.reason) body.appendChild(el('p', 'flag-card__reason', flag.reason));
      appendEvidence(body, flag);
      if (flag.neutral_rewrite) { body.append(el('p', 'flag-card__suggestion-label', 'Suggested neutral wording'), el('div', 'flag-card__suggestion', flag.neutral_rewrite)); }
      body.appendChild(el('small', '', 'Found by: ' + (flag.check || (item.page ? 'consistency check against the rest of the page' : 'audit')))); card.appendChild(body);
    } else {
      card.appendChild(el('div', 'flag-card__title', flag.title || labels[flag.kind] || 'Flag'));
      if (!isReviewed) card.appendChild(el('div', 'flag-card__preview', flag.reason || ''));
    }
    card.addEventListener('click', select); card.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }); return card;
  }
  function allItems() { return auditFlags.concat(pageFlags); }
  function anchorPageFlag(flag, index) {
    var view = $('.page-text-view'), quote = String(flag.context_sentence || flag.anchor_text || flag.related_anchor_text || '').trim(); if (!view || !quote) return null;
    var walker = document.createTreeWalker(view, NodeFilter.SHOW_TEXT), node;
    while ((node = walker.nextNode())) { var at = node.nodeValue.indexOf(quote); if (at < 0) continue; var after = node.splitText(at + quote.length), selected = node.splitText(at), mark = document.createElement('mark'); mark.className = 'page-anchor palimpsest-anchor'; mark.dataset.palimpsestId = 'page-' + index; selected.parentNode.replaceChild(mark, selected); mark.appendChild(selected); void after; return mark; }
    return null;
  }
  function rebuild() {
    table = $('#flags-diff table');
    if (table) {
      window.PalimpsestFlagsAnchoring.unwrap(table);
      var resolved = window.PalimpsestFlagsAnchoring.resolve(table, auditFlags.map(function (item) { return item.flag || item; }));
      auditFlags = resolved.anchored.map(function (row) { return { id: 'audit-' + row.flag.id, kind: row.flag.kind, tier: row.flag.tier, flag: row.flag, anchor: row.mark, anchors: row.marks }; });
      var tray = $('.flags-unanchored-tray'); tray.replaceChildren(); tray.hidden = !resolved.unanchored.length;
      if (resolved.unanchored.length) { var details = document.createElement('details'), summary = document.createElement('summary'); details.open = true; summary.textContent = 'Unanchored flags (' + resolved.unanchored.length + ')'; details.appendChild(summary); resolved.unanchored.forEach(function (flag) { details.appendChild(cardFor({ flag: flag }, true, function () {})); }); tray.appendChild(details); }
    }
    rail.update(allItems());
  }
  function summaryCount(items) { var admins = items.filter(function (item) { return item.flag.tier === 'admin'; }).length, reviews = items.length - admins, page = items.filter(function (item) { return item.page; }).length, parts = []; if (admins) parts.push(admins + ' Admin'); if (reviews) parts.push(reviews + ' Review'); return parts.join(' · ') + (page ? ' · ' + page + ' page consistency' : ''); }
  rail = window.PalimpsestRail.create({ root: root, summary: $('.flags-summary-bar'), workspace: $('.flags-workspace'), surface: $('.flags-diff-pane'), rail: $('.flags-rail'), list: $('.flags-rail__list'), kindLabel: function (kind) { return labels[kind] || kind; }, countText: summaryCount, filterAriaLabel: 'Filter flags by type', cardFor: cardFor });
  function stored(data) { return data.stored && data.stored_at ? 'Stored result from ' + data.stored_at : ''; }
  function receive(data) {
    var pane = $('.flags-diff-pane'), diff = $('#flags-diff');
    if (data.status !== 'ok') { if (diff) diff.remove(); pane.innerHTML = '<p class="flags-unavailable">' + esc(data.error || 'Audit unavailable') + '</p>'; auditFlags = []; rebuild(); return; }
    if (!diff) { diff = document.createElement('div'); diff.id = 'flags-diff'; pane.replaceChildren(diff); }
    if (data.diff_html) diff.innerHTML = data.diff_html; pane.querySelector('.flags-page-created-note') && pane.querySelector('.flags-page-created-note').remove();
    if (data.page_created) { var note = document.createElement('p'); note.className = 'flags-page-created-note'; note.textContent = 'Page created — the whole first version is treated as added text.' + (data.truncated ? ' Only the first part of this first version was checked.' : ''); pane.insertBefore(note, diff); }
    auditFlags = (Array.isArray(data.flags) ? data.flags : []).slice(); rebuild(); var status = $('#scan-status'); if (status) status.textContent = stored(data);
  }
  function renderSeverity() { var option = $('#flags-revision') && $('#flags-revision').selectedOptions[0], chips = $('.flags-severity-chips'); if (!option || !chips) return; chips.textContent = (option.dataset.admin || 0) + ' admin · ' + (option.dataset.review || 0) + ' review'; }
  async function audit(scan) { var status = $('#scan-status'); if (status) status.textContent = 'Checking revision…'; try { var response = await fetch(auditUrl('/api/flags/audit'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign(current(), { scan: scan })) }), data = await response.json(); if (!response.ok || data.status === 'error') throw Error(data.error || 'Audit unavailable'); receive(data); if (status) status.textContent = stored(data) || (data.status === 'ok' ? 'Audit loaded' : 'Not scanned'); } catch (error) { if (status) status.textContent = error.message; } }
  async function scanAll() { var select = $('#flags-revision'), original = select.value; for (var index = 0; index < select.options.length; index++) { select.selectedIndex = index; await audit(true); } select.value = original; await audit(false); }
  function receivePage(data) { var view = $('.page-text-view'), status = $('#page-status'), pane = $('.flags-diff-pane'); if (!view || !pane) return; view.innerHTML = data.page_html || ''; pane.appendChild(view); pageFlags = (Array.isArray(data.flags) ? data.flags : []).map(function (flag, index) { return { id: 'page-' + index, kind: flag.kind || 'OUT_OF_SYNC', tier: flag.tier, flag: flag, page: true, anchor: anchorPageFlag(flag, index) }; }).filter(function (item) { return item.anchor; }); rebuild(); if (status) status.textContent = stored(data) || (data.flags && data.flags.length ? data.flags.length + ' page consistency flags.' : 'No page consistency flags returned.'); }
  async function checkPage() { var status = $('#page-status'); if (status) status.textContent = 'Checking page consistency…'; try { var response = await fetch(auditUrl('/api/flags/page'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign(current(), { scan: true })) }), data = await response.json(); if (!response.ok || data.status === 'error') throw Error(data.error || 'Page consistency unavailable'); receivePage(data); } catch (error) { if (status) status.textContent = error.message; } }
  $('#flags-revision') && $('#flags-revision').addEventListener('change', function () { renderSeverity(); audit(false); }); $('#scan-revisions') && $('#scan-revisions').addEventListener('click', scanAll); $('#check-page') && $('#check-page').addEventListener('click', checkPage); renderSeverity(); try { var initial = JSON.parse($('#flags-data') ? $('#flags-data').textContent : 'null'); if (initial) receive(initial); } catch (_) {} if (new URLSearchParams(location.search).get('scan') === '1') scanAll();
}());

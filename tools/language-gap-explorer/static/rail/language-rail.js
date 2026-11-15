/* Reflows stored language findings into the shared current-edition rail shell. */
(function () {
  'use strict';
  function el(tag, cls, text) { var node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
  function reviewKey(item) { return 'palimpsest-language-reviewed-' + location.pathname + '-' + item.id; }
  function reviewed(item) { try { return localStorage.getItem(reviewKey(item)) === 'reviewed'; } catch (_) { return false; } }
  function setReviewed(item, value) { try { localStorage.setItem(reviewKey(item), value ? 'reviewed' : 'pending'); } catch (_) {} }
  function evidence(column, cls) {
    var wrap = el('div', 'language-rail-card__evidence ' + cls);
    if (!column) return wrap;
    var label = column.querySelector('.column-role');
    if (label) wrap.appendChild(label.cloneNode(true));
    Array.prototype.slice.call(column.querySelectorAll('.evidence-pane')).forEach(function (pane) { wrap.appendChild(pane.cloneNode(true)); });
    if (!wrap.children.length) wrap.appendChild(el('p', 'evidence-missing', 'No selected passage is available.'));
    return wrap;
  }
  function ready() {
    var panel = document.querySelector('.article-tabs-page #language-panel');
    if (!panel || !window.PalimpsestRail) return;
    var findings = Array.prototype.slice.call(panel.querySelectorAll('.finding'));
    if (!findings.length) return;
    var first = findings[0], parent = first.parentNode, workspace = document.createElement('div'), surface = document.createElement('div'), railNode = document.createElement('aside'), list = document.createElement('ol'), summary = document.createElement('aside');
    workspace.className = 'language-rail-workspace'; surface.className = 'language-reading-surface'; railNode.className = 'palimpsest-rail language-evidence-rail'; railNode.setAttribute('aria-label', 'Other-language evidence'); list.className = 'palimpsest-rail-list'; railNode.appendChild(list); summary.className = 'palimpsest-summary-bar language-summary-bar'; summary.setAttribute('aria-label', 'Palimpsest language-difference summary');
    parent.insertBefore(summary, first); parent.insertBefore(workspace, first); workspace.append(surface, railNode);
    findings.forEach(function (finding) { surface.appendChild(finding); });
    panel.querySelectorAll('.review-section').forEach(function (section) { if (!section.querySelector('.finding')) section.remove(); });
    var items = findings.map(function (finding, index) { var ours = finding.querySelector('.evidence-column[data-column="ours"]'), other = finding.querySelector('.evidence-column[data-column="theirs"]'), kind = finding.dataset.kind || 'uncertain'; return { id: finding.dataset.finding || String(index), kind: kind, finding: finding, ours: ours, other: other, anchor: ours || finding }; });
    function label(kind) { return ({ coverage: 'Coverage', framing: 'Framing', conflict: 'Possible contradiction', contradiction: 'Possible contradiction', uncertain: 'Review needed' })[kind] || kind; }
    function count(rows) { return rows.length + ' difference' + (rows.length === 1 ? '' : 's'); }
    function cardFor(item, expanded, select) {
      var card = document.createElement('article'), title = item.finding.querySelector('h3'), type = item.finding.querySelector('.finding-type'), isReviewed = reviewed(item);
      card.className = 'language-rail-card language-rail-card--' + item.kind + (isReviewed ? ' language-rail-card--reviewed' : ''); card.tabIndex = 0; card.setAttribute('role', 'button');
      var head = el('div', 'language-rail-card__meta'), chip = el('span', 'language-rail-card__type', type ? type.textContent : label(item.kind)), tier = el('span', 'language-rail-card__tier', item.kind === 'conflict' || item.kind === 'contradiction' ? 'Admin' : 'Review');
      var review = el('button', 'language-rail-card__review', isReviewed ? 'Reviewed' : 'Mark reviewed'); review.type = 'button'; review.setAttribute('aria-pressed', String(isReviewed)); review.addEventListener('click', function (event) { event.stopPropagation(); setReviewed(item, !isReviewed); controller.render(); }); head.append(chip, tier, review); card.append(head, el('div', 'language-rail-card__title', title ? title.textContent : label(item.kind)));
      if (expanded && !isReviewed) { card.append(evidence(item.ours, 'language-rail-card__current'), evidence(item.other, 'language-rail-card__other')); if (window.observeTranslations) window.observeTranslations(card); }
      card.addEventListener('click', select); card.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }); return card;
    }
    var controller = window.PalimpsestRail.create({ root: panel, summary: summary, workspace: workspace, surface: surface, rail: railNode, list: list, kindLabel: label, countText: count, filterAllLabel: 'Filter: All types ▾', filterAriaLabel: 'Filter differences by type', cardFor: cardFor, onVisibility: function (item, visible) { item.finding.hidden = !visible; } });
    controller.update(items);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
}());

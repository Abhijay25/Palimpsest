/* Shared Palimpsest summary bar and anchored-card rail for article tabs. */
(function (root) {
  'use strict';
  var ICONS = { FACT: '⚠', MOTIVE: '◉', FRAMING: '❝', REMOVED_CONTEXT: '−', HIDDEN_TEXT: '◌', CITATION_DATE: '◷', CITED_PAGE: '⌁', CHERRY_PICK: '❝', OUT_OF_SYNC: '↔', coverage: '+', framing: '❝', conflict: '⚠', contradiction: '⚠', uncertain: '?' };
  function el(tag, cls, text) { var node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
  function button(cls, text) { var node = el('button', cls, text); node.type = 'button'; return node; }
  function create(options) {
    var state = { items: [], active: null, filter: new Set(), filterOpen: false };
    var summary = options.summary, rail = options.rail, list = options.list || rail.querySelector('ol');
    var live = el('div', 'palimpsest-sr-live'); live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true'); options.root.appendChild(live);
    function kinds() { return Array.from(new Set(state.items.map(function (item) { return item.kind; }))); }
    function visible() { return state.items.filter(function (item) { return !state.filter.size || state.filter.has(item.kind); }); }
    function label(kind) { return options.kindLabel(kind); }
    function anchorsFor(item) { return item.anchors || (item.anchor ? [item.anchor] : []); }
    function activeItem() { return state.items.find(function (item) { return item.id === state.active; }); }
    function filterLabel() { var all = kinds(), selected = all.filter(function (kind) { return !state.filter.size || state.filter.has(kind); }); if (selected.length === all.length) return options.filterAllLabel || 'Filter: All types ▾'; if (selected.length <= 2) return 'Filter: ' + selected.map(label).join(', ') + ' ▾'; return 'Filter: ' + selected.length + ' types ▾'; }
    function scrollTo(item) { if (item && item.anchor) item.anchor.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); }
    function setActive(id, focus) { state.active = state.active === id ? null : id; render(); if (focus) scrollTo(activeItem()); }
    function select(id, focus) { state.active = id; render(); if (focus) scrollTo(activeItem()); }
    function navigate(step) { var rows = visible(); if (!rows.length) return; var index = rows.findIndex(function (item) { return item.id === state.active; }); select(rows[(index + step + rows.length) % rows.length].id, true); }
    function renderSummary() {
      summary.replaceChildren(); var all = state.items, shown = visible(); summary.hidden = !all.length; if (!all.length) return;
      summary.append(el('span', 'palimpsest-brand', 'Palimpsest'), el('span', 'palimpsest-summary-text', options.countText(all)));
      var filters = el('div', 'palimpsest-filters'), control = button('palimpsest-filter-control', filterLabel()), menu = el('div', 'palimpsest-filter-menu');
      control.setAttribute('aria-haspopup', 'true'); control.setAttribute('aria-expanded', String(state.filterOpen)); control.addEventListener('click', function () { state.filterOpen = !state.filterOpen; renderSummary(); });
      menu.hidden = !state.filterOpen; menu.setAttribute('role', 'group'); menu.setAttribute('aria-label', options.filterAriaLabel || 'Filter items by type');
      var actions = el('div', 'palimpsest-filter-actions'), allButton = button('palimpsest-quiet', 'Select all'), clear = button('palimpsest-quiet', 'Clear');
      allButton.addEventListener('click', function () { state.filter = new Set(); state.filterOpen = true; render(); });
      clear.addEventListener('click', function () { state.filter = new Set(kinds()); state.filterOpen = true; render(); });
      actions.append(allButton, clear); menu.appendChild(actions);
      kinds().forEach(function (kind) {
        var row = el('label', 'palimpsest-filter-option palimpsest-kind--' + String(kind).toLowerCase()), input = el('input'), count = state.items.filter(function (item) { return item.kind === kind; }).length;
        input.type = 'checkbox'; input.checked = !state.filter.size || state.filter.has(kind);
        input.addEventListener('change', function () { var next = state.filter.size ? new Set(state.filter) : new Set(kinds()); if (input.checked) next.add(kind); else next.delete(kind); state.filter = next.size === kinds().length ? new Set() : next; state.filterOpen = true; if (state.active && !visible().some(function (item) { return item.id === state.active; })) state.active = null; render(); });
        row.append(input, el('span', 'palimpsest-kind-icon', ICONS[kind] || '•'), document.createTextNode(label(kind) + ' (' + count + ')')); menu.appendChild(row);
      });
      menu.appendChild(el('p', 'palimpsest-filter-hint', 'No types selected means all types are shown.')); filters.append(control, menu); summary.appendChild(filters);
      var nav = el('div', 'palimpsest-nav'), previous = button('palimpsest-nav-button', '‹ Prev'), next = button('palimpsest-nav-button', 'Next ›'), position = shown.findIndex(function (item) { return item.id === state.active; });
      previous.setAttribute('aria-label', 'Previous item'); next.setAttribute('aria-label', 'Next item'); previous.disabled = next.disabled = shown.length <= 1; previous.addEventListener('click', function () { navigate(-1); }); next.addEventListener('click', function () { navigate(1); }); nav.append(previous, el('span', 'palimpsest-counter', (position < 0 ? '–' : position + 1) + ' of ' + shown.length), next); summary.appendChild(nav);
    }
    function setAnchorState(item, on) { anchorsFor(item).forEach(function (anchor) { anchor.classList.toggle('palimpsest-anchor-active', on); }); }
    function renderCards() {
      list.replaceChildren(); var rows = visible(); if (options.onVisibility) state.items.forEach(function (item) { options.onVisibility(item, rows.indexOf(item) !== -1); });
      rows.forEach(function (item) {
        var entry = el('li', 'palimpsest-rail-item'), expanded = item.id === state.active, card = options.cardFor(item, expanded, function () { setActive(item.id, true); });
        entry.dataset.palimpsestId = item.id; card.classList.add('palimpsest-card'); card.classList.toggle('is-expanded', expanded); card.setAttribute('aria-expanded', String(expanded)); card.id = 'palimpsest-card-' + item.id;
        anchorsFor(item).forEach(function (anchor) { anchor.setAttribute('aria-details', card.id); anchor.onclick = function (event) { event.preventDefault(); setActive(item.id, false); }; });
        card.addEventListener('mouseenter', function () { setAnchorState(item, true); }); card.addEventListener('mouseleave', function () { setAnchorState(item, expanded); }); card.addEventListener('focusin', function () { setAnchorState(item, true); }); card.addEventListener('focusout', function () { setAnchorState(item, expanded); }); setAnchorState(item, expanded); entry.appendChild(card); list.appendChild(entry);
      });
      live.textContent = rows.length ? options.countText(rows) + '. Use bracket keys to move between items.' : 'No items match this filter.'; requestAnimationFrame(layout);
    }
    function layout() {
      var compact = window.innerWidth < 1000 || options.workspace.clientWidth < 760; options.root.classList.toggle('palimpsest-compact', compact); if (compact) { rail.style.minHeight = ''; options.workspace.style.minHeight = ''; return; }
      var railTop = rail.getBoundingClientRect().top, items = Array.prototype.slice.call(list.children).map(function (node) { var item = state.items.find(function (row) { return row.id === node.dataset.palimpsestId; }), anchor = item && item.anchor; return { id: item.id, tier: item.tier || 'review', left: anchor ? anchor.getBoundingClientRect().left : 0, idealY: anchor ? Math.max(0, anchor.getBoundingClientRect().top - railTop) : 0, height: node.getBoundingClientRect().height || 80, node: node }; });
      var result = window.PalimpsestFlagsStacking && window.PalimpsestFlagsStacking.computePositions ? window.PalimpsestFlagsStacking.computePositions(items, state.active) : { items: items, height: options.surface.offsetHeight };
      result.items.forEach(function (item) { item.node.style.transform = 'translateY(' + item.y + 'px)'; }); var height = Math.max(options.surface.offsetHeight, result.height || 0); rail.style.minHeight = height + 'px'; options.workspace.style.minHeight = height + 'px';
    }
    function render() { renderSummary(); renderCards(); }
    document.addEventListener('keydown', function (event) { if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable]')) return; if (event.key === 'Escape' && state.filterOpen) { state.filterOpen = false; renderSummary(); return; } if (event.key === 'Escape' && state.active) { state.active = null; render(); return; } if (event.key === ']' || event.key === 'j') { event.preventDefault(); navigate(1); } if (event.key === '[' || event.key === 'k') { event.preventDefault(); navigate(-1); } });
    document.addEventListener('pointerdown', function (event) { if (state.filterOpen && !event.target.closest('.palimpsest-filters')) { state.filterOpen = false; renderSummary(); } }); window.addEventListener('resize', layout); window.addEventListener('load', layout); if (window.ResizeObserver) new ResizeObserver(function () { requestAnimationFrame(layout); }).observe(options.workspace); if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { requestAnimationFrame(layout); });
    return { update: function (items) { state.items = items || []; if (!state.items.some(function (item) { return item.id === state.active; })) state.active = null; render(); }, select: select, render: render, layout: layout };
  }
  root.PalimpsestRail = { create: create };
}(window));

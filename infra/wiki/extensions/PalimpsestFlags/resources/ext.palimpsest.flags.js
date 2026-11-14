( function () {
	'use strict';
	var A = typeof require === 'function' ? require( './anchoring.js' ) : window.PalimpsestFlagsAnchoring;
	var S = typeof require === 'function' ? require( './stacking.js' ) : window.PalimpsestFlagsStacking;
	/* ResourceLoader loads Vue 3 and Codex. CSS-only Codex markup keeps this enhancement
	 * usable when the diff is re-rendered outside Vue's lifecycle. */
	var Vue, Codex, Icons;
	if ( typeof require === 'function' ) { Vue = require( 'vue' ); Codex = require( './codex.js' ); Icons = require( './icons.json' ); }
	if ( !A || !S || !window.mw || !mw.config ) { return; }
	var cfg = mw.config.get( 'wgPalimpsestFlags' );
	if ( !cfg || !cfg.oldid || !cfg.diff ) { return; }
	var table, root, workspace, rail, list, summary, tray, live, state = { flags: [], anchored: [], unanchored: [], active: null, reviewed: new Set(), filter: null, layout: 'rail', trigger: null, response: null };
	var kindLabel = { FACT: 'Fact', MOTIVE: 'Motive', FRAMING: 'Wording', REMOVED_CONTEXT: 'Removed context', HIDDEN_TEXT: 'Hidden text', CITATION_DATE: 'Citation date', CITED_PAGE: 'Cited page' };
	var kindIcon = { FACT: 'cdxIconAlert', MOTIVE: 'cdxIconUserTalk', FRAMING: 'cdxIconQuotes', REMOVED_CONTEXT: 'cdxIconSubtract', HIDDEN_TEXT: 'cdxIconEyeClosed', CITATION_DATE: 'cdxIconClock', CITED_PAGE: 'cdxIconReference' };
	function el( tag, cls, text ) { var n = document.createElement( tag ); if ( cls ) { n.className = cls; } if ( text !== undefined ) { n.textContent = text; } return n; }
	function button( cls, label ) { var b = el( 'button', cls, label ); b.type = 'button'; return b; }
	function safeUrl( url ) { try { var parsed = new URL( url, location.href ); return /^https?:$/.test( parsed.protocol ) ? parsed.href : null; } catch ( e ) { return null; } }
	function icon( kind ) { var host = el( 'span', 'pf-chip__icon' ), name = kindIcon[ kind ]; if ( Vue && Codex && Icons && Codex.CdxIcon && Icons[ name ] ) { Vue.createApp( { render: function () { return Vue.h( Codex.CdxIcon, { icon: Icons[ name ] } ); } } ).mount( host ); } return host; }
	function mode() { return window.innerWidth >= 1000 && workspace.clientWidth >= ( table.classList.contains( 'mw-diff-inline' ) ? 760 : 900 ) ? 'rail' : 'compact'; }
	function visibleFlags() { return state.anchored.filter( function ( row ) { return !state.filter || row.flag.kind === state.filter; } ); }
	function setLive( text ) { live.textContent = text; }
	function setup() {
		table = document.querySelector( 'table.diff' ); if ( !table || table.closest( '.pf-root' ) ) { return false; }
		root = el( 'div', 'pf-root' ); summary = el( 'aside', 'pf-summary-bar' ); summary.setAttribute( 'aria-label', 'Palimpsest audit summary' ); tray = el( 'section', 'pf-unanchored-tray' ); workspace = el( 'div', 'pf-workspace' ); rail = el( 'aside', 'pf-rail' ); rail.setAttribute( 'aria-label', 'Palimpsest flags' ); list = el( 'ol', 'pf-rail__list' ); rail.appendChild( list ); live = el( 'div', 'pf-sr-live' ); live.setAttribute( 'role', 'status' ); live.setAttribute( 'aria-live', 'polite' ); live.setAttribute( 'aria-atomic', 'true' );
		table.parentNode.insertBefore( root, table ); root.append( summary, tray, workspace, live ); workspace.append( table, rail );
		new ResizeObserver( relayout ).observe( workspace ); new ResizeObserver( relayout ).observe( table ); window.addEventListener( 'resize', updateMode ); document.fonts && document.fonts.ready && document.fonts.ready.then( relayout );
		mw.hook && mw.hook( 'wikipage.diff' ).add( function () { updateMode(); relayout(); } ); document.addEventListener( 'keydown', shortcuts ); return true;
	}
	function loading() { root.dataset.pfState = 'loading'; summary.replaceChildren(); var spinner = el( 'div', 'cdx-progress-indicator pf-progress' ); spinner.setAttribute( 'role', 'progressbar' ); if ( Vue && Codex && Codex.CdxProgressIndicator ) { Vue.createApp( { render: function () { return Vue.h( Codex.CdxProgressIndicator ); } } ).mount( spinner ); } summary.append( spinner, el( 'span', '', 'Checking this edit…' ) ); window.setTimeout( function () { if ( root.dataset.pfState === 'loading' ) { summary.lastChild.textContent = 'Still checking cited sources…'; } }, 5000 ); }
	function api( retry ) {
		loading(); var controller = new AbortController(), timedOut = false, timer = window.setTimeout( function () { timedOut = true; controller.abort(); }, 35000 );
		var params = new URLSearchParams( { action: 'palimpsestflags', format: 'json', formatversion: '2', oldid: String( cfg.oldid ), diff: String( cfg.diff ) } );
		fetch( mw.util.wikiScript( 'api' ) + '?' + params, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } } ).then( function ( response ) { if ( !response.ok ) { throw new Error( 'http' ); } return response.json(); } ).then( function ( json ) {
			window.clearTimeout( timer ); var data = json.palimpsestflags;
			if ( !data || data.status !== 'ok' || Number( cfg.oldid ) !== Number( mw.config.get( 'wgDiffOldId' ) || cfg.oldid ) || Number( cfg.diff ) !== Number( mw.config.get( 'wgDiffNewId' ) || cfg.diff ) ) { throw new Error( data && data.error || 'stale' ); }
			state.response = data; receive( data );
		} ).catch( function () { window.clearTimeout( timer ); error( timedOut ? 'Audit unavailable' : 'Audit unavailable' ); } );
		void retry;
	}
	function receive( data ) {
		A.unwrap( table ); state.flags = Array.isArray( data.flags ) ? data.flags : []; var resolved = A.resolve( table, state.flags ); state.anchored = resolved.anchored; state.unanchored = resolved.unanchored; root.dataset.pfState = state.flags.length ? 'ready' : 'empty'; updateMode(); renderSummary(); renderTray(); renderCards();
		var admins = state.flags.filter( function ( f ) { return f.tier === 'admin'; } ).length, reviews = state.flags.length - admins;
		setLive( state.flags.length ? 'Palimpsest found ' + admins + ' admin flags and ' + reviews + ' review flags. Press right bracket for next flag.' : 'No issues flagged.' );
	}
	function error( message ) { root.dataset.pfState = 'error'; summary.replaceChildren(); summary.append( chip( 'warning', message ), retryButton() ); rail.replaceChildren( list ); tray.hidden = true; setLive( message ); }
	function retryButton() { var b = button( 'cdx-button cdx-button--weight-quiet', 'Retry' ); b.addEventListener( 'click', function () { api( true ); } ); return b; }
	function chip( status, label ) { var c = el( 'span', 'cdx-info-chip cdx-info-chip--' + status ); if ( Vue && Codex && Codex.CdxInfoChip ) { Vue.createApp( { render: function () { return Vue.h( Codex.CdxInfoChip, { status: status }, { default: function () { return label; } } ); } } ).mount( c ); } else { c.appendChild( el( 'span', 'cdx-info-chip__text', label ) ); } return c; }
	function kbd( text ) { return el( 'kbd', 'pf-kbd', text ); }
	function renderSummary() {
		summary.replaceChildren(); var brand = el( 'span', 'pf-brand', 'Palimpsest' ); summary.append( brand );
		if ( !state.flags.length ) { summary.append( el( 'span', 'pf-summary__text pf-summary__text--ok', '✓ No issues flagged in this edit' ) ); floatBar(); return; }
		var admins = state.flags.filter( function ( f ) { return f.tier === 'admin'; } ).length, reviews = state.flags.length - admins, parts = [];
		if ( admins ) { parts.push( admins + ' for admin review' ); } if ( reviews ) { parts.push( reviews + ' worth a look' ); }
		summary.append( el( 'span', 'pf-summary__text', state.flags.length + ( state.flags.length === 1 ? ' flag' : ' flags' ) + ' · ' + parts.join( ' · ' ) ) );
		var filters = el( 'div', 'pf-filters' ); filters.setAttribute( 'role', 'group' ); filters.setAttribute( 'aria-label', 'Filter flags by type' );
		Object.keys( kindLabel ).forEach( function ( kind ) { var count = state.flags.filter( function ( f ) { return f.kind === kind; } ).length; if ( !count ) { return; } var b = button( 'pf-filter pf-kind--' + kind.toLowerCase(), '' ); b.append( el( 'span', 'pf-dot' ), document.createTextNode( kindLabel[ kind ] + ' ' + count ) ); b.title = 'Show only ' + kindLabel[ kind ].toLowerCase() + ' flags'; b.setAttribute( 'aria-pressed', String( state.filter === kind ) ); b.addEventListener( 'click', function () { state.filter = state.filter === kind ? null : kind; renderSummary(); renderCards(); } ); filters.appendChild( b ); } );
		summary.append( filters );
		var nav = el( 'div', 'pf-nav' ), previous = button( 'cdx-button cdx-button--weight-quiet pf-nav__btn', '' ), next = button( 'cdx-button cdx-button--action-progressive cdx-button--weight-primary pf-nav__btn', '' );
		previous.append( document.createTextNode( '‹ Prev ' ), kbd( '[' ) ); next.append( document.createTextNode( 'Next › ' ), kbd( ']' ) ); previous.title = 'Previous flag ([ or k)'; next.title = 'Next flag (] or j)';
		previous.addEventListener( 'click', function () { navigate( -1 ); } ); next.addEventListener( 'click', function () { navigate( 1 ); } );
		nav.append( previous, el( 'span', 'pf-counter', counter() ), next ); summary.append( nav );
		if ( state.response && state.response.partial ) { summary.append( chip( 'warning', 'Partial check (some sources timed out)' ), retryButton() ); }
		floatBar();
	}
	// Keep the bar visible while the admin scrolls through a long diff: pin it under the
	// Vector sticky header once its natural position leaves the viewport.
	var placeholder = null;
	function floatBar() {
		if ( !root || !summary ) { return; }
		if ( !placeholder ) { placeholder = el( 'div', 'pf-summary-placeholder' ); root.insertBefore( placeholder, summary ); window.addEventListener( 'scroll', floatBar, { passive: true } ); window.addEventListener( 'resize', floatBar ); }
		var header = document.querySelector( '.vector-sticky-header-visible .vector-sticky-header, .vector-sticky-header.vector-sticky-header-visible' );
		var top = header ? header.getBoundingClientRect().bottom : 0, anchor = placeholder.getBoundingClientRect(), box = root.getBoundingClientRect();
		var floating = anchor.top < top && box.bottom > top + summary.offsetHeight + 40;
		summary.classList.toggle( 'pf-summary-bar--floating', floating );
		placeholder.style.height = floating ? summary.offsetHeight + 'px' : '0';
		if ( floating ) { summary.style.top = top + 'px'; summary.style.left = box.left + 'px'; summary.style.width = box.width + 'px'; } else { summary.style.top = summary.style.left = summary.style.width = ''; }
	}
	function counter() { var flags = visibleFlags(), index = flags.findIndex( function ( row ) { return row.flag.id === state.active; } ); return ( index < 0 ? '–' : index + 1 ) + ' of ' + flags.length; }
	function renderTray() { tray.replaceChildren(); tray.hidden = !state.unanchored.length; if ( tray.hidden ) { return; } var details = el( 'details', 'pf-unanchored-details' ); details.open = true; details.appendChild( el( 'summary', '', 'Unanchored flags (' + state.unanchored.length + ')' ) ); state.unanchored.forEach( function ( flag ) { details.appendChild( cardFor( flag, false ) ); } ); tray.appendChild( details ); }
	function cardFor( flag, railCard ) {
		var reviewed = state.reviewed.has( flag.id ), article = el( 'article', 'pf-card pf-card--' + flag.kind.toLowerCase() + ' pf-card--' + flag.tier + ( reviewed ? ' pf-card--reviewed' : '' ) ); article.id = 'pf-card-' + flag.id;
		var head = el( 'div', 'pf-card__head' ), kind = el( 'span', 'cdx-info-chip pf-chip pf-kind--' + flag.kind.toLowerCase() ); kind.dataset.tier = flag.tier; kind.append( icon( flag.kind ), document.createTextNode( kindLabel[ flag.kind ] || flag.kind ) ); head.append( kind, el( 'strong', 'pf-tier', flag.tier === 'admin' ? 'Admin' : 'Review' ) ); if ( flag.side === 'old' ) { head.appendChild( el( 'span', 'pf-old', '← OLD' ) ); }
		var review = button( 'cdx-button cdx-button--icon-only cdx-button--weight-quiet pf-reviewed', '✓' ); review.setAttribute( 'aria-label', 'Mark reviewed' ); review.setAttribute( 'aria-pressed', String( reviewed ) ); review.addEventListener( 'click', function ( e ) { e.stopPropagation(); toggleReviewed( flag.id ); } ); head.appendChild( review );
		var toggle = button( 'pf-card__toggle', '' ), title = el( 'div', 'pf-card__title', flag.title ); if ( flag.occurrences > 1 ) { title.append( document.createTextNode( ' ×' + flag.occurrences ) ); } toggle.setAttribute( 'aria-expanded', String( state.active === flag.id ) ); toggle.setAttribute( 'aria-controls', 'pf-body-' + flag.id ); toggle.append( head, title, el( 'div', 'pf-card__preview', flag.reason ) ); toggle.addEventListener( 'click', function () { activate( flag.id, toggle ); } ); article.appendChild( toggle );
		if ( state.active === flag.id && !reviewed ) { article.appendChild( fullBody( flag ) ); }
		if ( railCard ) { article.dataset.pfId = flag.id; } return article;
	}
	function section( label, child ) { var wrap = el( 'section', 'pf-section' ); wrap.append( el( 'h4', 'pf-section__label', label ), child ); return wrap; }
	function fullBody( flag ) {
		var body = el( 'div', 'pf-card__body' ); body.id = 'pf-body-' + flag.id;
		body.append( el( 'span', 'pf-confidence', ( flag.confidence >= .8 ? 'High confidence ' : flag.confidence >= .5 ? 'Medium confidence ' : 'Low confidence ' ) + Math.round( flag.confidence * 100 ) + '%' ) );
		body.append( section( 'Why it may need review', el( 'p', 'pf-reason', flag.reason ) ) );
		var quotes = ( flag.evidence || [] ).filter( function ( item ) { return item.quote && item.quote.trim(); } );
		var sourceBox = el( 'div', 'pf-sources' );
		quotes.forEach( function ( item ) { sourceBox.append( el( 'blockquote', 'pf-evidence', item.quote ) ); } );
		var seen = {}, links = el( 'div', 'pf-citations' );
		( flag.citations || [] ).concat( quotes.map( function ( q ) { return q.url; } ) ).forEach( function ( url ) { var href = safeUrl( url ); if ( href && !seen[ href ] ) { seen[ href ] = true; var a = el( 'a', 'pf-citation', new URL( href ).hostname ); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = href; links.appendChild( a ); } } );
		if ( links.childNodes.length ) { sourceBox.append( links ); }
		if ( !quotes.length && flag.check === 'judge' ) { sourceBox.prepend( el( 'p', 'pf-muted', 'No source text was available to check this claim against.' ) ); }
		if ( sourceBox.childNodes.length ) { body.append( section( quotes.length ? 'What the source says' : 'Source', sourceBox ) ); }
		if ( flag.neutral_rewrite ) { body.append( section( 'Suggested neutral wording', el( 'div', 'pf-rewrite', flag.neutral_rewrite ) ) ); }
		body.appendChild( el( 'div', 'pf-card__footer pf-muted', 'Found by: ' + ( { judge: 'source comparison', stealth: 'hidden-text scan', citation_dates: 'citation date check', render: 'cited page scan', citation_lifecycle: 'cited page history check' }[ flag.check ] || flag.check ) ) ); return body;
	}
	function renderCards() {
		list.replaceChildren(); if ( state.layout !== 'rail' || !state.flags.length ) { renderPins(); return; } rail.hidden = false; visibleFlags().forEach( function ( row ) { var li = el( 'li', 'pf-rail__item' ); li.dataset.pfId = row.flag.id; li.appendChild( cardFor( row.flag, true ) ); list.appendChild( li ); } ); relayout();
	}
	function renderPins() { rail.hidden = true; Array.prototype.slice.call( table.querySelectorAll( '.pf-inline-pin' ) ).forEach( function ( pin ) { pin.remove(); } ); if ( state.layout === 'rail' ) { return; } visibleFlags().forEach( function ( row, index ) { var pin = button( 'pf-inline-pin', String( index + 1 ) ); pin.setAttribute( 'aria-label', 'Flag ' + ( index + 1 ) + ', ' + row.flag.tier + ' ' + row.flag.kind + ': ' + row.flag.title ); pin.addEventListener( 'click', function () { activate( row.flag.id, pin ); } ); row.mark.after( pin ); } ); }
	function relayout() { if ( !root || state.layout !== 'rail' || !state.flags.length ) { return; } var railTop = rail.getBoundingClientRect().top, items = Array.prototype.slice.call( list.children ).map( function ( li ) { var row = state.anchored.find( function ( x ) { return x.flag.id === li.dataset.pfId; } ), rect = li.getBoundingClientRect(); return { id: row.flag.id, tier: row.flag.tier, idealY: row.mark.getBoundingClientRect().top - railTop, left: row.mark.getBoundingClientRect().left, height: rect.height || 80, node: li }; } ); var result = S.computePositions( items, state.active ); result.items.forEach( function ( item ) { item.node.style.transform = 'translateY(' + item.y + 'px)'; } ); rail.style.minHeight = result.height + 'px'; }
	function updateMode() { if ( !root ) { return; } var next = mode(); if ( next !== state.layout ) { state.layout = next; root.dataset.pfMode = next; renderCards(); } }
	function highlight( id, on ) { Array.prototype.slice.call( table.querySelectorAll( 'mark[data-pf-id="' + CSS.escape( id ) + '"]' ) ).forEach( function ( mark ) { mark.classList.toggle( 'pf-anchor--active', on ); } ); }
	function activate( id, trigger ) { state.trigger = trigger || state.trigger; state.active = state.active === id ? null : id; highlight( id, state.active === id ); renderSummary(); renderCards(); renderTray(); if ( state.active ) { focusMark( id, false ); if ( state.layout === 'compact' ) { popover( id, state.trigger ); } } else { closePopover(); } }
	function focusMark( id, focus ) { var mark = table.querySelector( 'mark[data-pf-id="' + CSS.escape( id ) + '"]' ); if ( !mark ) { return; } var r = mark.getBoundingClientRect(); if ( r.top < 60 || r.bottom > innerHeight - 80 ) { mark.scrollIntoView( { behavior: matchMedia( '(prefers-reduced-motion: reduce)' ).matches ? 'auto' : 'smooth', block: 'center' } ); } if ( focus !== false ) { mark.focus(); } }
	function popover( id, trigger ) { closePopover(); var row = state.anchored.find( function ( r ) { return r.flag.id === id; } ); if ( !row ) { return; } var pop = el( 'div', 'cdx-popover pf-popover' ); pop.setAttribute( 'role', 'dialog' ); pop.appendChild( cardFor( row.flag, false ) ); document.body.appendChild( pop ); var rect = ( trigger || row.mark ).getBoundingClientRect(); pop.style.left = Math.max( 8, Math.min( innerWidth - 348, rect.left ) ) + 'px'; pop.style.top = Math.min( innerHeight - pop.offsetHeight - 8, rect.bottom + 8 ) + 'px'; }
	function closePopover() { var p = document.querySelector( '.pf-popover' ); if ( p ) { p.remove(); } }
	function toggleReviewed( id ) { if ( state.reviewed.has( id ) ) { state.reviewed.delete( id ); } else { state.reviewed.add( id ); } renderCards(); renderSummary(); }
	function navigate( step ) { var flags = visibleFlags().filter( function ( r ) { return !state.reviewed.has( r.flag.id ); } ); if ( !flags.length ) { return; } var current = flags.findIndex( function ( r ) { return r.flag.id === state.active; } ); activate( flags[ ( current + step + flags.length ) % flags.length ].flag.id ); }
	function shortcuts( event ) { if ( event.ctrlKey || event.altKey || event.metaKey || event.target.closest( 'input,textarea,select,[contenteditable]' ) ) { return; } if ( event.key === ']' || event.key === 'j' ) { event.preventDefault(); navigate( 1 ); } else if ( event.key === '[' || event.key === 'k' ) { event.preventDefault(); navigate( -1 ); } else if ( event.key === 'x' && state.active ) { event.preventDefault(); toggleReviewed( state.active ); navigate( 1 ); } else if ( event.key === 'Escape' && state.active ) { var trigger = state.trigger; state.active = null; renderCards(); renderSummary(); closePopover(); trigger && trigger.focus(); } }
	function init() { if ( setup() ) { state.layout = mode(); root.dataset.pfMode = state.layout; api( false ); } }
	if ( document.readyState === 'loading' ) { document.addEventListener( 'DOMContentLoaded', init ); } else { init(); }
}() );

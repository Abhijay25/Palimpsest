( function ( root, factory ) {
	'use strict';
	var api = factory();
	if ( typeof module === 'object' && module.exports ) { module.exports = api; }
	root.PalimpsestFlagsAnchoring = api;
}( typeof globalThis !== 'undefined' ? globalThis : window, function () {
	'use strict';
	function normalize( text ) { return String( text || '' ).replace( /\u00a0/g, ' ' ).replace( /\s+/g, ' ' ).trim(); }
	function sideCells( table, side ) {
		var inline = table.classList.contains( 'mw-diff-inline' );
		var selectors = inline ? ( side === 'old' ? 'td.mw-diff-inline-deleted,td.mw-diff-inline-changed,td.mw-diff-inline-context' : 'td.mw-diff-inline-added,td.mw-diff-inline-changed,td.mw-diff-inline-context' ) : ( side === 'old' ? 'td.diff-deletedline,td.diff-context' : 'td.diff-addedline,td.diff-context' );
		return Array.prototype.slice.call( table.querySelectorAll( selectors ) );
	}
	function textNodes( cell, side, inline ) {
		var nodes = [], walker = document.createTreeWalker( cell, NodeFilter.SHOW_TEXT, { acceptNode: function ( node ) {
			var parent = node.parentElement;
			if ( !parent || parent.closest( '.pf-anchor,.pf-inline-pin,.pf-zw-badge' ) ) { return NodeFilter.FILTER_REJECT; }
			if ( inline && ( side === 'old' ? parent.closest( 'ins' ) : parent.closest( 'del' ) ) ) { return NodeFilter.FILTER_REJECT; }
			return NodeFilter.FILTER_ACCEPT;
		} } );
		while ( walker.nextNode() ) { nodes.push( walker.currentNode ); }
		return nodes;
	}
	function indexCell( cell, side, inline ) {
		var nodes = textNodes( cell, side, inline ), text = '', parts = [];
		nodes.forEach( function ( node ) { var start = text.length; text += node.nodeValue; parts.push( { node: node, start: start, end: text.length } ); } );
		return { cell: cell, text: text, normalized: normalize( text ), parts: parts };
	}
	function overlapScore( source, context ) {
		if ( !context ) { return 0; }
		var grams = {}, score = 0, normalized = normalize( context );
		for ( var i = 0; i + 2 < normalized.length; i++ ) { grams[ normalized.slice( i, i + 3 ) ] = true; }
		for ( var j = 0; j + 2 < source.length; j++ ) { if ( grams[ source.slice( j, j + 3 ) ] ) { score++; } }
		return score;
	}
	// Model quotes are prose; diff cells show wikitext. Match the quote's words in order while
	// allowing link targets, brackets, bold/italic quotes and asterisks between them.
	function markupTolerant( entries, anchor, flag ) {
		var tokens = normalize( anchor ).match( /[\p{L}\p{N}]+|[^\s\p{L}\p{N}]/gu ) || [];
		if ( tokens.filter( function ( t ) { return /[\p{L}\p{N}]/u.test( t ); } ).length < 2 ) { return []; }
		var gap = "(?:\\s|\\[\\[[^\\]|]*\\||[\\[\\]'*|])*", found = [];
		var pattern = new RegExp( tokens.map( function ( t ) { return t.replace( /[.*+?^${}()|[\]\\]/g, '\\$&' ); } ).join( gap ), 'gu' );
		entries.forEach( function ( entry, order ) {
			var m; pattern.lastIndex = 0;
			while ( ( m = pattern.exec( entry.text ) ) !== null ) { found.push( { entry: entry, start: m.index, end: m.index + m[ 0 ].length, order: order, score: overlapScore( entry.normalized, flag.context_sentence ) } ); if ( m[ 0 ].length === 0 ) { pattern.lastIndex++; } }
		} );
		return found;
	}
	function findMatch( entries, flag ) {
		var anchor = String( flag.anchor_text || '' );
		if ( !anchor ) { return null; }
		var exact = [];
		entries.forEach( function ( entry, order ) {
			var start = entry.text.indexOf( anchor );
			while ( start !== -1 ) { exact.push( { entry: entry, start: start, end: start + anchor.length, order: order, score: overlapScore( entry.normalized, flag.context_sentence ) } ); start = entry.text.indexOf( anchor, start + 1 ); }
		} );
		if ( !exact.length ) { exact = markupTolerant( entries, anchor, flag ); }
		if ( !exact.length ) { return null; }
		var approx = Number.isInteger( flag.anchor_start ) ? 1 + flag.anchor_start / 80 : 0;
		exact.sort( function ( a, b ) {
			var changedA = a.entry.cell.querySelector( 'ins.diffchange,del.diffchange' ) ? 1 : 0;
			var changedB = b.entry.cell.querySelector( 'ins.diffchange,del.diffchange' ) ? 1 : 0;
			return ( b.score - a.score ) || ( changedB - changedA ) || ( Math.abs( a.order - approx ) - Math.abs( b.order - approx ) ) || ( a.order - b.order );
		} );
		return exact[ 0 ];
	}
	function wrap( match, flag ) {
		var ranges = [];
		match.entry.parts.forEach( function ( part ) {
			var from = Math.max( part.start, match.start ), to = Math.min( part.end, match.end );
			if ( from < to ) { ranges.push( { node: part.node, start: from - part.start, end: to - part.start } ); }
		} );
		var marks = [];
		ranges.reverse().forEach( function ( range, index ) {
			var node = range.node, after = node.splitText( range.end ), selected = node.splitText( range.start ), mark = document.createElement( 'mark' );
			mark.className = 'pf-anchor pf-anchor--' + String( flag.kind || '' ).toLowerCase();
			mark.dataset.pfId = flag.id; mark.id = index === ranges.length - 1 ? 'pf-mark-' + flag.id : '';
			mark.tabIndex = 0; mark.setAttribute( 'aria-details', 'pf-card-' + flag.id );
			selected.parentNode.replaceChild( mark, selected ); mark.appendChild( selected ); marks.unshift( mark );
			void after;
		} );
		return marks;
	}
	function resolve( table, flags ) {
		var result = { anchored: [], unanchored: [] }, inline = table.classList.contains( 'mw-diff-inline' );
		flags.forEach( function ( flag ) {
			var entries = sideCells( table, flag.side ).map( function ( cell ) { return indexCell( cell, flag.side, inline ); } );
			var match = findMatch( entries, flag );
			if ( !match ) { result.unanchored.push( flag ); return; }
			var marks = wrap( match, flag );
			if ( marks.length ) {
				if ( flag.related_anchor_text ) { var related = findMatch( entries, Object.assign( {}, flag, { anchor_text: flag.related_anchor_text } ) ); if ( related ) { wrap( related, flag ).forEach( function ( mark ) { mark.classList.add( 'pf-anchor--related' ); mark.dataset.pfRelatedId = flag.id; } ); } }
				result.anchored.push( { flag: flag, marks: marks, mark: marks[ 0 ] } );
			} else { result.unanchored.push( flag ); }
		} );
		return result;
	}
	function unwrap( table ) { Array.prototype.slice.call( table.querySelectorAll( 'mark.pf-anchor' ) ).forEach( function ( mark ) { mark.replaceWith( ...Array.prototype.slice.call( mark.childNodes ) ); } ); Array.prototype.slice.call( table.querySelectorAll( '.pf-inline-pin' ) ).forEach( function ( pin ) { pin.remove(); } ); }
	return { normalize: normalize, sideCells: sideCells, resolve: resolve, unwrap: unwrap, findMatch: findMatch };
} ) );

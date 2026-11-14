( function ( root, factory ) {
	'use strict'; var api = factory(); if ( typeof module === 'object' && module.exports ) { module.exports = api; } root.PalimpsestFlagsStacking = api;
}( typeof globalThis !== 'undefined' ? globalThis : window, function () {
	'use strict';
	function computePositions( items, activeId, gap ) {
		gap = gap === undefined ? 8 : gap;
		var ordered = items.slice().sort( function ( a, b ) { return ( a.idealY - b.idealY ) || ( a.left - b.left ) || ( ( a.tier === 'admin' ? 0 : 1 ) - ( b.tier === 'admin' ? 0 : 1 ) ) || String( a.id ).localeCompare( String( b.id ) ); } );
		if ( !ordered.length ) { return { items: ordered, height: 0 }; }
		var active = ordered.findIndex( function ( item ) { return item.id === activeId; } );
		if ( active < 0 ) { ordered.forEach( function ( item, i ) { item.y = i ? Math.max( item.idealY, ordered[ i - 1 ].y + ordered[ i - 1 ].height + gap ) : Math.max( 0, item.idealY ); } ); }
		else {
			ordered[ active ].y = Math.max( 0, ordered[ active ].idealY );
			for ( var i = active - 1; i >= 0; i-- ) { ordered[ i ].y = Math.min( ordered[ i ].idealY, ordered[ i + 1 ].y - ordered[ i ].height - gap ); }
			// Keep the selected card exactly at its source. Cards above may extend
			// into the rail's leading overflow; clipping it would break the spatial
			// promise made when navigating a dense hunk.
			for ( var k = active + 1; k < ordered.length; k++ ) { ordered[ k ].y = Math.max( ordered[ k ].idealY, ordered[ k - 1 ].y + ordered[ k - 1 ].height + gap ); }
		}
		return { items: ordered, height: ordered[ ordered.length - 1 ].y + ordered[ ordered.length - 1 ].height };
	}
	return { computePositions: computePositions };
} ) );

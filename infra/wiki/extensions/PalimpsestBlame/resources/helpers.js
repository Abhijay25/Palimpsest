(function (root, factory) {
	'use strict';
	var helpers = factory();
	if (typeof module === 'object' && module.exports) {
		module.exports = helpers;
	}
	if (root) {
		root.PalimpsestBlameHelpers = helpers;
	}
}(typeof window !== 'undefined' ? window : globalThis, function () {
	'use strict';

	var MONTHS = {
		january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
		july: 7, august: 8, september: 9, october: 10, november: 11, december: 12
	};

	function pad2( value ) {
		return String( value ).padStart( 2, '0' );
	}

	function utcStamp( year, month, day, endOfDay ) {
		var date = new Date( Date.UTC( year, month - 1, day, endOfDay ? 23 : 0,
			endOfDay ? 59 : 0, endOfDay ? 59 : 0 ) );
		if ( date.getUTCFullYear() !== year || date.getUTCMonth() + 1 !== month || date.getUTCDate() !== day ) {
			throw new Error( 'Enter a real calendar date.' );
		}
		return date.toISOString().replace( '.000Z', 'Z' );
	}

	function parseDate( input ) {
		var match, month, year, day;
		var value = String( input || '' ).trim();
		match = /^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/.exec( value );
		if ( !match || !( match[ 2 ].toLowerCase() in MONTHS ) ) {
			throw new Error( 'Use a date such as 15 March 2026.' );
		}
		day = Number( match[ 1 ] );
		month = MONTHS[ match[ 2 ].toLowerCase() ];
		year = Number( match[ 3 ] );
		return { year: year, month: month, day: day };
	}

	function interpretDateQuery( input ) {
		var value = String( input || '' ).trim();
		var match = /^as\s+of\s+(.+)$/i.exec( value );
		if ( match ) {
			var asOf = parseDate( match[ 1 ] );
			return {
				mode: 'asof', from: null,
				to: utcStamp( asOf.year, asOf.month, asOf.day, true ),
				rule: 'Latest revision at or before this UTC day-end.'
			};
		}
		match = /^latest\s+version\s+before\s+(.+)$/i.exec( value );
		if ( match ) {
			var before = parseDate( match[ 1 ] );
			return {
				mode: 'before', from: null,
				to: utcStamp( before.year, before.month, before.day, false ),
				rule: 'Latest revision strictly before this UTC day begins.'
			};
		}
		match = /^between\s+(.+?)\s+and\s+(.+)$/i.exec( value );
		if ( match ) {
			var last = parseDate( match[ 2 ] );
			var firstText = /\b\d{4}$/.test( match[ 1 ].trim() ) ? match[ 1 ] : match[ 1 ] + ' ' + last.year;
			var first = parseDate( firstText );
			var from = utcStamp( first.year, first.month, first.day, false );
			var to = utcStamp( last.year, last.month, last.day, true );
			if ( from > to ) {
				throw new Error( 'The start date must not be after the end date.' );
			}
			return { mode: 'range', from: from, to: to, rule: 'Edits in this inclusive UTC date range, newest first.' };
		}
		throw new Error( 'Try “As of 15 March 2026”, “Between 1 February and 31 March 2026”, or “Latest version before 1 April 2026”.' );
	}

	function manualDateQuery( mode, fromValue, toValue ) {
		if ( mode !== 'range' && mode !== 'asof' && mode !== 'before' ) {
			throw new Error( 'Choose as-of, strictly-before, or range mode.' );
		}
		function fromControl( value, start ) {
			var match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/.exec( value || '' );
			if ( !match ) {
				throw new Error( 'Enter both date and time fields in UTC.' );
			}
			var hour = +( match[ 4 ] || ( start ? 0 : 23 ) );
			var minute = +( match[ 5 ] || ( start ? 0 : 59 ) );
			if ( hour > 23 || minute > 59 ) {
				throw new Error( 'Enter a valid UTC hour (00–23) and minute (00–59).' );
			}
			var date = new Date( Date.UTC( +match[ 1 ], +match[ 2 ] - 1, +match[ 3 ], hour, minute, start ? 0 : 59 ) );
			if ( date.getUTCFullYear() !== +match[ 1 ] || date.getUTCMonth() + 1 !== +match[ 2 ] || date.getUTCDate() !== +match[ 3 ] ) {
				throw new Error( 'Enter a real calendar date and time.' );
			}
			return date.toISOString().replace( '.000Z', 'Z' );
		}
		if ( mode === 'range' ) {
			var start = fromControl( fromValue, true );
			var end = fromControl( toValue, false );
			if ( start > end ) {
				throw new Error( 'The start must not be after the end.' );
			}
			return { mode: mode, from: start, to: end, rule: 'Edits in this inclusive UTC range, newest first.' };
		}
		var bound = fromControl( toValue || fromValue, mode === 'before' );
		return { mode: mode, from: null, to: bound, rule: mode === 'before' ? 'Latest revision strictly before this UTC bound.' : 'Latest revision at or before this UTC bound.' };
	}

	function validOffsetElement( element ) {
		if ( !element || !element.hasAttribute || !element.hasAttribute( 'data-pb-start' ) || !element.hasAttribute( 'data-pb-end' ) ) {
			return null;
		}
		var start = Number( element.getAttribute( 'data-pb-start' ) );
		var end = Number( element.getAttribute( 'data-pb-end' ) );
		if ( !Number.isInteger( start ) || !Number.isInteger( end ) || start < 0 || end < start || element.textContent.length !== end - start ) {
			return null;
		}
		return { start: start, end: end, element: element };
	}

	function closestMapped( node ) {
		var element = node && ( node.nodeType === 1 ? node : node.parentElement );
		while ( element ) {
			var mapped = validOffsetElement( element );
			if ( mapped ) {
				return mapped;
			}
			element = element.parentElement;
		}
		return null;
	}

	function utf16Before( container, offset, mappedElement ) {
		var range = document.createRange();
		range.selectNodeContents( mappedElement );
		range.setEnd( container, offset );
		return range.toString().length;
	}

	function selectionRanges( selection ) {
		var ranges = [], unmapped = [], fragments = [], exactText = selection ? selection.toString() : '';
		if ( !selection || selection.rangeCount === 0 || !exactText ) {
			return { ranges: ranges, unmapped: unmapped, fragments: fragments, exactText: exactText };
		}
		for ( var index = 0; index < selection.rangeCount; index++ ) {
			var range = selection.getRangeAt( index );
			var walker = document.createTreeWalker( range.commonAncestorContainer, NodeFilter.SHOW_TEXT );
			var textNodes = [];
			if ( range.commonAncestorContainer.nodeType === 3 ) {
				textNodes.push( range.commonAncestorContainer );
			} else {
				var next;
				while ( ( next = walker.nextNode() ) ) {
					textNodes.push( next );
				}
			}
			var walkedText = '';
			textNodes.forEach( function ( node ) {
				if ( !range.intersectsNode( node ) ) {
					return;
				}
				var textRange = document.createRange();
				textRange.selectNodeContents( node );
				if ( node === range.startContainer ) {
					textRange.setStart( node, range.startOffset );
				}
				if ( node === range.endContainer ) {
					textRange.setEnd( node, range.endOffset );
				}
				var selected = textRange.toString();
				if ( !selected ) {
					return;
				}
				walkedText += selected;
				var fragment = { text: selected, start: null, end: null };
				var mapped = closestMapped( node );
				if ( !mapped ) {
					if ( /\S/u.test( selected ) ) {
						unmapped.push( { text: selected, reason: 'This text has no verified source offset.' } );
					}
					fragments.push( fragment );
					return;
				}
				var startWithin;
				try {
					startWithin = utf16Before( node, textRange.startOffset, mapped.element );
				} catch ( error ) {
					unmapped.push( { text: selected, reason: 'This selection crosses a source mapping boundary.' } );
					fragments.push( fragment );
					return;
				}
				var start = mapped.start + startWithin;
				var end = start + selected.length;
				if ( end > mapped.end ) {
					unmapped.push( { text: selected, reason: 'Visible text exceeds its verified source range.' } );
					fragments.push( fragment );
					return;
				}
				var last = ranges[ ranges.length - 1 ];
				var uniquelyMapped = true;
				if ( last && last.end === start ) {
					last.end = end;
				} else if ( last && start < last.end ) {
					unmapped.push( { text: selected, reason: 'This selection overlaps source ranges that cannot be mapped uniquely.' } );
					uniquelyMapped = false;
				} else {
					ranges.push( { start: start, end: end } );
				}
				if ( uniquelyMapped ) {
					fragment.start = start;
					fragment.end = end;
				}
				fragments.push( fragment );
			} );
			if ( walkedText.replace( /\s/gu, '' ) !== range.toString().replace( /\s/gu, '' ) ) {
				unmapped.push( { text: '', reason: 'The selection includes rendered content without a verified source text node.' } );
			}
		}
		return { ranges: ranges, unmapped: unmapped, fragments: fragments, exactText: exactText };
	}

	function safeHttpUrl( value ) {
		try {
			var base = typeof window !== 'undefined' && window.location ? window.location.href : 'http://localhost/';
			var url = new URL( value, base );
			return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
		} catch ( error ) {
			return null;
		}
	}

	function revisionIndex( data ) {
		var map = new Map();
		( data.revisions || [] ).forEach( function ( revision ) {
			map.set( String( revision.revision_id ), revision );
		} );
		return map;
	}

	function validCoalescedTokenRanges( span ) {
		if ( !Array.isArray( span.token_ranges ) || !span.token_ranges.length || !Array.isArray( span.lineage_ids ) ) {
			return false;
		}
		var ownerPrefix = String( span.revision_id ) + ':';
		var ownIds = new Set();
		var previousEnd = span.start;
		for ( var i = 0; i < span.token_ranges.length; i++ ) {
			var range = span.token_ranges[ i ];
			if ( !Array.isArray( range ) || range.length !== 3 || !Number.isInteger( range[ 0 ] ) || !Number.isInteger( range[ 1 ] ) || range[ 0 ] !== previousEnd || range[ 1 ] <= range[ 0 ] || range[ 1 ] > span.end || typeof range[ 2 ] !== 'string' || !range[ 2 ].startsWith( ownerPrefix ) || ownIds.has( range[ 2 ] ) ) {
				return false;
			}
			ownIds.add( range[ 2 ] );
			previousEnd = range[ 1 ];
		}
		if ( previousEnd !== span.end || span.token_id !== span.token_ranges[ 0 ][ 2 ] ) {
			return false;
		}
		return Array.from( ownIds ).every( function ( id ) { return span.lineage_ids.includes( id ); } );
	}

	function validateAnalyzeResponse( data, expectedRevision ) {
		if ( !data || typeof data !== 'object' || data.status !== 'ready' ) {
			return 'The Blame service did not return a ready analysis.';
		}
		if ( !data.page || !data.snapshot || !Number.isInteger( Number( data.snapshot.revision_id ) ) || Number( data.snapshot.revision_id ) <= 0 ) {
			return 'The analysis is missing its page or local snapshot revision.';
		}
		if ( expectedRevision && Number( data.snapshot.revision_id ) !== Number( expectedRevision ) ) {
			return 'The article and attribution refer to different revisions. Reload this snapshot to retry.';
		}
		if ( typeof data.source_text !== 'string' || typeof data.html !== 'string' || !data.coverage ||
			typeof data.coverage.history_complete !== 'boolean' || !Array.isArray( data.spans ) ||
			!Array.isArray( data.revisions ) || !Array.isArray( data.events ) || !data.algorithm || !data.mapping ) {
			return 'The analysis is missing required source, mapping, history, or coverage fields.';
		}
		for ( var i = 0; i < data.spans.length; i++ ) {
			var span = data.spans[ i ];
			if ( !span || !Number.isInteger( span.start ) || !Number.isInteger( span.end ) || span.start < 0 || span.end <= span.start || span.end > data.source_text.length || !Number.isInteger( Number( span.revision_id ) ) || Number( span.revision_id ) <= 0 ) {
				return 'The analysis contains an invalid UTF-16 source span.';
			}
			if ( Object.prototype.hasOwnProperty.call( span, 'token_ranges' ) && !validCoalescedTokenRanges( span ) ) {
				return 'The analysis contains invalid coalesced UTF-16 token ranges.';
			}
		}
		return null;
	}

	return {
		interpretDateQuery: interpretDateQuery,
		manualDateQuery: manualDateQuery,
		selectionRanges: selectionRanges,
		validOffsetElement: validOffsetElement,
		safeHttpUrl: safeHttpUrl,
		revisionIndex: revisionIndex,
		validateAnalyzeResponse: validateAnalyzeResponse
	};
}));

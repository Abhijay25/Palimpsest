( function () {
	'use strict';

	var H = window.PalimpsestBlameHelpers;
	var root = document.getElementById( 'palimpsest-blame' );
	if ( !root || !H || !window.mw || !mw.config ) {
		return;
	}

	var config = mw.config.get( [ 'wgPageName', 'wgRevisionId', 'wgArticleId', 'wgCanonicalSpecialPageName' ] );
	var title = config.wgPageName;
	var originalRootParent = root.parentNode;
	var originalRootNextSibling = root.nextSibling;
	var actionRevision = Number( root.dataset.revision );
	if ( !Number.isInteger( actionRevision ) || actionRevision <= 0 ) {
		actionRevision = null;
	}
	var configuredRevision = Number( config.wgRevisionId );
	if ( !Number.isInteger( configuredRevision ) || configuredRevision <= 0 ) {
		configuredRevision = null;
	}
	var snapshotTargetConflict = actionRevision && configuredRevision && actionRevision !== configuredRevision;
	var initialRevision = actionRevision || configuredRevision;
	var apiUrl = mw.util.wikiScript( 'api' );
	var sequence = 0;
	var activeController = null;
	var currentData = null;
	var currentHost = root;
	var renderedRevision = null;
	var retainedArticleSelection = null;
	var returnFocus = null;
	var returnFocusAnchor = null;
	var selectedText = '';
	var revisionPalette = new Map();
	var paletteCategoryCount = 8;
	var article = document.querySelector( '#mw-content-text .mw-parser-output' );
	var language = document.documentElement.lang || 'unknown';

	function element( name, className, text ) {
		var node = document.createElement( name );
		if ( className ) {
			node.className = className;
		}
		if ( text !== undefined ) {
			node.textContent = text;
		}
		return node;
	}

	function link( label, href, className ) {
		var safe = H.safeHttpUrl( href );
		if ( !safe ) {
			return null;
		}
		var anchor = element( 'a', className, label );
		anchor.href = safe;
		anchor.rel = 'noopener noreferrer';
		return anchor;
	}

	function setState( state, message, retry, build ) {
		root.setAttribute( 'data-state', state );
		root.replaceChildren();
		var status = element( 'p', 'pb-status', message );
		status.setAttribute( 'role', state === 'error' ? 'alert' : 'status' );
		root.appendChild( status );
		if ( retry ) {
			var button = element( 'button', 'pb-button', 'Retry analysis' );
			button.type = 'button';
			button.addEventListener( 'click', function () {
				startAnalysis( null );
			} );
			root.appendChild( button );
		}
		if ( build ) {
			var buildButton = element( 'button', 'pb-button', 'Prepare attribution' );
			buildButton.type = 'button';
			buildButton.addEventListener( 'click', queueBuild );
			root.appendChild( buildButton );
		}
	}

	function mayRetry( data ) {
		return Boolean( data && ( data.retryable === true || data.job && data.job.retryable === true || data.status === 'pending' ) );
	}

	function mayPrepare( data ) {
		return Boolean( data && data.buildable === true );
	}

	function apiRequest( params, method, signal ) {
		params = Object.assign( { action: 'palimpsestblame', format: 'json', formatversion: 2, title: title }, params );
		var options = { credentials: 'same-origin', method: method || 'GET', signal: signal, headers: { Accept: 'application/json' } };
		if ( options.method === 'GET' ) {
			var query = new URLSearchParams( params );
			return fetch( apiUrl + '?' + query.toString(), options ).then( readResponse );
		}
		var token = mw.user && mw.user.tokens && mw.user.tokens.get( 'csrfToken' );
		if ( !token ) {
			return Promise.reject( new Error( 'A CSRF token is unavailable for this request.' ) );
		}
		params.token = token;
		options.headers[ 'Content-Type' ] = 'application/x-www-form-urlencoded; charset=UTF-8';
		options.body = new URLSearchParams( params );
		return fetch( apiUrl, options ).then( readResponse );
	}

	function readResponse( response ) {
		if ( !response.ok ) {
			throw new Error( 'The Blame service returned HTTP ' + response.status + '.' );
		}
		return response.json().then( function ( data ) {
			if ( data.error ) {
				throw new Error( data.error.info || data.error.code || 'The Blame request failed.' );
			}
			return data.palimpsestblame || data;
		} );
	}

	function revisionParam() {
		return Number.isInteger( initialRevision ) && initialRevision > 0 ? initialRevision : undefined;
	}

	function declaredJobRevisions( data ) {
		return [ data && data.snapshot && data.snapshot.revision_id, data && data.revision_id, data && data.job && data.job.revision_id ]
			.filter( function ( value ) {
				var revision = Number( value );
				return Number.isInteger( revision ) && revision > 0;
			} )
			.map( Number );
	}

	function pinJobRevision( data ) {
		var revisions = declaredJobRevisions( data );
		if ( !revisions.length ) {
			return 'The pending job did not identify its target revision.';
		}
		var target = revisions[ 0 ];
		if ( revisions.some( function ( revision ) { return revision !== target; } ) ) {
			return 'The pending job response contains conflicting target revisions.';
		}
		var expected = revisionParam() || currentData && Number( currentData.snapshot.revision_id );
		if ( expected && target !== expected ) {
			return 'The pending job targets revision ' + target + ', but this view is pinned to revision ' + expected + '.';
		}
		initialRevision = expected || target;
		return null;
	}

	function pinResponseRevision( data ) {
		var revisions = declaredJobRevisions( data );
		if ( !revisions.length ) {
			return null;
		}
		var target = revisions[ 0 ];
		if ( revisions.some( function ( revision ) { return revision !== target; } ) ) {
			return 'The response contains conflicting target revisions.';
		}
		var expected = revisionParam() || currentData && Number( currentData.snapshot.revision_id );
		if ( expected && target !== expected ) {
			return 'The response refers to revision ' + target + ', but this view is pinned to revision ' + expected + '.';
		}
		if ( !initialRevision ) {
			initialRevision = target;
		}
		return null;
	}

	function validateJobRevision( data ) {
		var revisions = declaredJobRevisions( data );
		var expected = revisionParam();
		if ( revisions.some( function ( revision ) { return revision !== expected; } ) || new Set( revisions ).size > 1 ) {
			return 'The job status response refers to a different or conflicting revision.';
		}
		return null;
	}

	function selectionFromAnalysis( data, selection ) {
		var tokenIds = new Set();
		var revisionIds = new Set();
		var ambiguous = false;
		( data.spans || [] ).forEach( function ( span ) {
			var overlappingRanges = Array.isArray( span.token_ranges ) ? span.token_ranges.filter( function ( tokenRange ) {
				return Array.isArray( tokenRange ) && tokenRange.length >= 3 && selection.ranges.some( function ( range ) {
					return Number( tokenRange[ 0 ] ) < range.end && Number( tokenRange[ 1 ] ) > range.start;
				} );
			} ) : null;
			if ( overlappingRanges && !overlappingRanges.length || !overlappingRanges && !selection.ranges.some( function ( range ) { return span.start < range.end && span.end > range.start; } ) ) {
				return;
			}
			if ( overlappingRanges ) {
				var spanTokenIds = new Set( span.token_ranges.map( function ( tokenRange ) { return String( tokenRange[ 2 ] ); } ) );
				overlappingRanges.forEach( function ( tokenRange ) { tokenIds.add( String( tokenRange[ 2 ] ) ); } );
				( span.lineage_ids || [] ).forEach( function ( id ) {
					if ( !spanTokenIds.has( String( id ) ) ) {
						tokenIds.add( String( id ) );
					}
				} );
			} else {
				tokenIds.add( String( span.token_id ) );
				( span.lineage_ids || [] ).forEach( function ( id ) { tokenIds.add( String( id ) ); } );
			}
			revisionIds.add( Number( span.revision_id ) );
			ambiguous = ambiguous || span.ambiguous === true;
		} );
		var events = eventsForTokenIds( data.events, tokenIds );
		return {
			ranges: selection.ranges,
			revision_ids: Array.from( revisionIds ),
			events: events,
			ambiguous: ambiguous || events.some( function ( event ) { return event.ambiguous === true; } ),
			reasons: selection.unmapped ? selection.unmapped.map( function ( item ) { return item.reason; } ) : []
		};
	}

	function beginRequest() {
		sequence++;
		if ( activeController ) {
			activeController.abort();
		}
		activeController = new AbortController();
		return { id: sequence, signal: activeController.signal };
	}

	function selectionIsInArticle( selection ) {
		if ( !article || !selection || !selection.rangeCount ) {
			return false;
		}
		for ( var i = 0; i < selection.rangeCount; i++ ) {
			if ( !article.contains( selection.getRangeAt( i ).commonAncestorContainer ) ) {
				return false;
			}
		}
		return true;
	}

	function readArticleSelection() {
		var nativeSelection = window.getSelection();
		if ( !nativeSelection || nativeSelection.isCollapsed || !nativeSelection.rangeCount ) {
			return null;
		}
		if ( selectionCrossesInterface( nativeSelection ) ) {
			retainedArticleSelection = null;
			return null;
		}
		if ( !selectionIsInArticle( nativeSelection ) ) {
			retainedArticleSelection = null;
			return null;
		}
		var snapshot = H.selectionRanges( nativeSelection );
		snapshot.statement = nearestStatement( nativeSelection );
		retainedArticleSelection = snapshot;
		return snapshot;
	}

	function selectionCrossesInterface( selection ) {
		if ( !selection || !selection.rangeCount || !article || !article.contains( root ) ) {
			return false;
		}
		for ( var i = 0; i < selection.rangeCount; i++ ) {
			if ( selection.getRangeAt( i ).intersectsNode( root ) ) {
				return true;
			}
		}
		return false;
	}

	function showSelectionGuard() {
		var panel = root.querySelector( '.pb-breakdown' ) || root;
		if ( panel.querySelector( '.pb-selection-error' ) ) {
			return;
		}
		var message = element( 'p', 'pb-warning pb-selection-error', 'This selection crosses the inline history controls. Close history, then select article text again.' );
		message.setAttribute( 'role', 'alert' );
		panel.appendChild( message );
	}

	function rememberReturnFocus( node ) {
		returnFocus = node;
		var mapping = H.validOffsetElement( node );
		returnFocusAnchor = mapping ? { start: mapping.start, end: mapping.end, text: node.textContent } : null;
	}

	function resolveReturnFocus() {
		if ( returnFocus && returnFocus.isConnected ) {
			return returnFocus;
		}
		if ( returnFocusAnchor && article ) {
			var candidates = article.querySelectorAll( '[data-pb-start][data-pb-end]' );
			for ( var i = 0; i < candidates.length; i++ ) {
				var mapping = H.validOffsetElement( candidates[ i ] );
				if ( mapping && mapping.start === returnFocusAnchor.start && mapping.end === returnFocusAnchor.end && candidates[ i ].textContent === returnFocusAnchor.text ) {
					return candidates[ i ];
				}
			}
		}
		return root.querySelector( '.pb-action-bar button' );
	}

	document.addEventListener( 'selectionchange', function () {
		var nativeSelection = window.getSelection();
		if ( nativeSelection && !nativeSelection.isCollapsed ) {
			readArticleSelection();
		}
	} );

	function isCurrent( request ) {
		return request.id === sequence && !request.signal.aborted;
	}

	function startAnalysis( selection ) {
		if ( selection && selection.ranges.length > 64 ) {
			showIncompleteSelection( selection, 'This selection contains more than 64 separate verified source ranges. Select a smaller passage; no partial analysis was requested.' );
			return;
		}
		if ( selection && selection.unmapped && selection.unmapped.length ) {
			retainedArticleSelection = null;
			showIncompleteSelection( selection );
			return;
		}
		retainedArticleSelection = null;
		var request = beginRequest();
		setState( 'loading', 'Loading verified revision history…' );
		var params = { op: 'analyze' };
		var revision = revisionParam();
		if ( revision ) {
			params.revision = revision;
		}
		if ( selection && selection.ranges.length ) {
			params.ranges = JSON.stringify( selection.ranges );
		}
		apiRequest( params, 'GET', request.signal ).then( function ( data ) {
			if ( !isCurrent( request ) ) {
				return;
			}
			if ( data.status === 'pending' && data.job && data.job.id ) {
				var pendingRevisionError = pinJobRevision( data );
				if ( pendingRevisionError ) {
					setState( 'error', pendingRevisionError, false, false );
					return;
				}
				return pollJob( data.job.id, request, selection );
			}
			showResponse( data, selection, request );
		} ).catch( function ( error ) {
			if ( isCurrent( request ) && error.name !== 'AbortError' ) {
				var retryable = error.retryable === true || error.buildAvailable === true || error.retryable === undefined && error.buildAvailable === undefined;
				setState( 'error', error.message || 'The revision history could not be loaded.', retryable, error.buildAvailable === true );
			}
		} );
	}

	function pollJob( jobId, request, selection ) {
		var attempts = 0;
		function poll() {
			if ( !isCurrent( request ) ) {
				return Promise.reject( new Error( 'This history request is no longer current.' ) );
			}
			if ( attempts++ >= 30 ) {
				var timeoutError = new Error( 'Attribution preparation is still running. Retry to check its progress.' );
				timeoutError.retryable = true;
				return Promise.reject( timeoutError );
			}
			return apiRequest( { op: 'status', revision: revisionParam(), jobid: jobId }, 'GET', request.signal ).then( function ( status ) {
				if ( !isCurrent( request ) ) {
					return null;
				}
				var revisionError = validateJobRevision( status );
				if ( revisionError ) {
					throw new Error( revisionError );
				}
				var jobState = status.job && status.job.status || status.status;
				if ( jobState === 'ready' ) {
					return status.status === 'ready' && status.snapshot && typeof status.source_text === 'string' ? status : null;
				}
				if ( jobState === 'failed' || jobState === 'unavailable' ) {
					var jobError = new Error( status.job && status.job.reason || 'History analysis could not be completed.' );
					jobError.retryable = mayRetry( status );
					jobError.buildAvailable = mayPrepare( status );
					throw jobError;
				}
				var progress = status.job && Number.isFinite( status.job.processed ) ? ' (' + status.job.processed + ( status.job.total ? '/' + status.job.total : '' ) + ' revisions)' : ' (' + attempts + '/30 checks)';
				setState( 'pending', 'Preparing attribution' + progress + '…' );
				return new Promise( function ( resolve ) {
					window.setTimeout( resolve, 800 );
				} ).then( poll );
			} );
		}
		return poll().then( function ( readyAnalysis ) {
			if ( isCurrent( request ) ) {
				if ( readyAnalysis ) {
					if ( selection && !readyAnalysis.selection ) {
						readyAnalysis.selection = selectionFromAnalysis( readyAnalysis, selection );
					}
					showResponse( readyAnalysis, selection || null, request );
				} else {
					startAnalysis( selection || null );
				}
			}
		} );
	}

	function showResponse( data, selection, request ) {
		var responseRevisionError = pinResponseRevision( data );
		if ( responseRevisionError ) {
			setState( 'error', responseRevisionError, false, false );
			return;
		}
		if ( !data || data.status === 'unavailable' || data.status === 'failed' ) {
			setState( 'error', data && data.reason || 'Verified attribution is unavailable for this revision.', mayRetry( data ), mayPrepare( data ) );
			return;
		}
		var invalid = H.validateAnalyzeResponse( data, revisionParam() );
		if ( invalid ) {
			setState( 'error', invalid, true, false );
			return;
		}
		if ( renderedRevision !== null && renderedRevision !== Number( data.snapshot.revision_id ) ) {
			retainedArticleSelection = null;
		}
		if ( !initialRevision ) {
			initialRevision = Number( data.snapshot.revision_id );
		}
		currentData = data;
		buildRevisionPalette( data );
		if ( !article ) {
			var content = document.getElementById( 'mw-content-text' );
			if ( content ) {
				article = document.createElement( 'div' );
				article.className = 'mw-parser-output';
				content.insertBefore( article, root.parentNode === content ? root : null );
			}
		}
		if ( data.html && article && renderedRevision !== Number( data.snapshot.revision_id ) ) {
			if ( article.contains( root ) && article.parentNode ) {
				article.parentNode.insertBefore( root, article.nextSibling );
			}
			installSnapshotHtml( data.html );
			renderedRevision = Number( data.snapshot.revision_id );
		}
		buildActionBar();
		if ( selection ) {
			selectedText = selection.exactText;
			openBreakdown( data, selection );
		} else {
			renderFull( data );
		}
	}

	function installSnapshotHtml( html ) {
		var parsed = new DOMParser().parseFromString( '<!doctype html><body>' + html, 'text/html' );
		parsed.querySelectorAll( 'script, iframe, object, embed, form, base' ).forEach( function ( node ) {
			node.remove();
		} );
		parsed.querySelectorAll( '*' ).forEach( function ( node ) {
			Array.from( node.attributes ).forEach( function ( attr ) {
				if ( /^on/i.test( attr.name ) || attr.name === 'srcdoc' || attr.name === 'style' || attr.name === 'srcset' ) {
					node.removeAttribute( attr.name );
				} else if ( [ 'href', 'src', 'xlink:href', 'formaction' ].includes( attr.name.toLowerCase() ) && !H.safeHttpUrl( attr.value ) && !attr.value.startsWith( '/' ) && !attr.value.startsWith( '#' ) ) {
					node.removeAttribute( attr.name );
				}
			} );
		} );
		article.replaceChildren.apply( article, Array.from( parsed.body.childNodes ) );
		bindHighlights();
	}

	function buildActionBar() {
		root.replaceChildren();
		root.className = 'palimpsest-blame';
		root.setAttribute( 'data-state', 'ready' );
		var bar = element( 'div', 'pb-action-bar' );
		var inspect = element( 'button', 'pb-button pb-primary', 'Inspect selected text' );
		inspect.type = 'button';
		inspect.setAttribute( 'aria-label', 'Inspect selected article text' );
		inspect.addEventListener( 'mousedown', function ( event ) {
			event.preventDefault();
		} );
		inspect.addEventListener( 'pointerdown', function () {
			readArticleSelection();
		} );
		inspect.addEventListener( 'click', function () {
			if ( selectionCrossesInterface( window.getSelection() ) ) {
				retainedArticleSelection = null;
				showSelectionGuard();
				return;
			}
			var selection = readArticleSelection() || retainedArticleSelection;
			if ( selection ) {
				selection = Object.assign( {}, selection, { ranges: selection.ranges.slice(), unmapped: selection.unmapped.slice() } );
			}
			if ( !selection || !selection.exactText ) {
				restoreRootPosition();
				renderFull( currentData );
				var instruction = element( 'p', 'pb-warning pb-selection-incomplete', 'Select text in the article first.' );
				instruction.setAttribute( 'role', 'alert' );
				root.appendChild( instruction );
				return;
			}
			if ( selection.ranges.length === 0 ) {
				showIncompleteSelection( selection, 'This selection has no verified source offsets. Try a highlighted passage.' );
				return;
			}
			if ( selection.ranges.length > 64 ) {
				showIncompleteSelection( selection, 'This selection contains more than 64 separate verified source ranges. Select a smaller passage; no partial analysis was requested.' );
				return;
			}
			selection.statement = selection.statement || nearestStatement( window.getSelection() );
			rememberReturnFocus( inspect );
			startAnalysis( selection );
		} );
		bar.appendChild( inspect );
		var titleNode = element( 'span', 'pb-action-label', 'Trace this wording through verified revisions' );
		bar.appendChild( titleNode );
		root.appendChild( bar );
		if ( currentData ) {
			renderCoverage( currentData );
		}
	}

	function queueBuild() {
		if ( !revisionParam() ) {
			setState( 'error', 'An exact article revision is required before attribution can be prepared.', false, false );
			return;
		}
		var request = beginRequest();
		setState( 'pending', 'Starting bounded attribution preparation…' );
		var revision = revisionParam();
		var params = { op: 'build' };
		if ( revision ) {
			params.revision = revision;
		}
		apiRequest( params, 'POST', request.signal ).then( function ( data ) {
			if ( !isCurrent( request ) ) {
				return;
			}
			if ( !data.job || !data.job.id ) {
				throw new Error( 'The build request did not return a job ID.' );
			}
			var revisionError = pinJobRevision( data );
			if ( revisionError ) {
				throw new Error( revisionError );
			}
			return pollJob( data.job.id, request, null );
		} ).catch( function ( error ) {
			if ( isCurrent( request ) && error.name !== 'AbortError' ) {
				var retryable = error.retryable === true || error.buildAvailable === true || error.retryable === undefined && error.buildAvailable === undefined;
				setState( 'error', error.message || 'Attribution preparation could not start.', retryable, error.buildAvailable === true );
			}
		} );
	}

	function bindHighlights() {
		if ( !article ) {
			return;
		}
		article.querySelectorAll( '[data-pb-start][data-pb-end]' ).forEach( function ( node ) {
			var mapping = H.validOffsetElement( node );
			if ( !mapping || node.dataset.pbBound === '1' ) {
				return;
			}
			node.dataset.pbBound = '1';
			node.classList.add( 'pb-attributed' );
			var interactive = node.closest( 'a, button, input, select, textarea, [role="button"]' );
			var revisionIds = new Set();
			( currentData && currentData.spans || [] ).forEach( function ( span ) {
				if ( span.end > mapping.start && span.start < mapping.end ) {
					revisionIds.add( String( span.revision_id ) );
				}
			} );
			if ( revisionIds.size === 1 ) {
				var id = Array.from( revisionIds )[ 0 ];
				node.dataset.pbRevisionId = id;
				applyRevisionColor( node, id );
			} else if ( revisionIds.size > 1 ) {
				node.classList.add( 'pb-mixed' );
			}
			var revision = revisionIds.size === 1 && H.revisionIndex( currentData ).get( Array.from( revisionIds )[ 0 ] );
			if ( interactive ) {
				return;
			}
			node.setAttribute( 'tabindex', '0' );
			node.setAttribute( 'role', 'button' );
				node.setAttribute( 'aria-label', 'Inspect wording changed in revision ' + ( revision ? revision.revision_id + ' by ' + ( revision.user || 'an unavailable identity' ) + ' on ' + formatUtc( revision.timestamp ) : 'with unavailable history' ) + ': ' + node.textContent );
			var activate = function () {
				var selection = readArticleSelection() || retainedArticleSelection;
				var intersects = selection && selection.ranges.some( function ( range ) { return range.end > mapping.start && range.start < mapping.end; } );
				if ( !intersects ) {
					selection = { exactText: node.textContent, ranges: [ { start: mapping.start, end: mapping.end } ], unmapped: [], fragments: [ { text: node.textContent, start: mapping.start, end: mapping.end } ], statement: node.closest( 'p, li, blockquote, h1, h2, h3, h4, h5, h6, dt, dd, figcaption' ) };
				}
				rememberReturnFocus( node );
				startAnalysis( selection );
			};
			node.addEventListener( 'click', activate );
			node.addEventListener( 'keydown', function ( event ) {
				if ( event.key === 'Enter' || event.key === ' ' ) {
					event.preventDefault();
					activate();
				}
			} );
		} );
	}

	function buildRevisionPalette( data ) {
		var ownerIds = new Set();
		( data.spans || [] ).forEach( function ( span ) { ownerIds.add( String( span.revision_id ) ); } );
		var allIds = new Set( ownerIds );
		( data.revisions || [] ).forEach( function ( revision ) { allIds.add( String( revision.revision_id ) ); } );
		( data.events || [] ).forEach( function ( event ) { allIds.add( String( event.revision_id ) ); } );
		var sortIds = function ( ids ) { return Array.from( ids ).sort( function ( left, right ) {
			var difference = Number( left ) - Number( right );
			return Number.isFinite( difference ) && difference !== 0 ? difference : left.localeCompare( right );
		} ); };
		var orderedOwners = sortIds( ownerIds );
		var orderedHistory = sortIds( new Set( Array.from( allIds ).filter( function ( id ) { return !ownerIds.has( id ); } ) ) );
		var ordered = orderedOwners.concat( orderedHistory );
		var categories = Array.from( { length: paletteCategoryCount }, function () { return []; } );
		var idsByColor = new Map();
		ordered.forEach( function ( id, index ) {
			var colorIndex = index % paletteCategoryCount;
			categories[ colorIndex ].push( id );
			idsByColor.set( id, colorIndex );
		} );
		revisionPalette = new Map();
		ordered.forEach( function ( id ) {
			var colorIndex = idsByColor.get( id );
			var members = categories[ colorIndex ];
			revisionPalette.set( id, {
				index: colorIndex,
				label: 'Color category ' + ( colorIndex + 1 ) + ( members.length > 1 ? ' (shared)' : '' )
			} );
		} );
	}

	function colorInfo( revisionId ) {
		return revisionPalette.get( String( revisionId ) ) || { index: 0, label: 'Color category 1' };
	}

	function applyRevisionColor( node, revisionId ) {
		var color = colorInfo( revisionId );
		node.dataset.pbColorIndex = String( color.index );
		node.dataset.pbColorLabel = color.label;
	}

	function selectedQuoteParts( data, selection ) {
		var parts = [];
		( selection.fragments || [] ).forEach( function ( fragment ) {
			if ( !Number.isInteger( fragment.start ) || !Number.isInteger( fragment.end ) || fragment.end <= fragment.start || fragment.end - fragment.start !== fragment.text.length ) {
				parts.push( { text: fragment.text, revisionId: null, start: null, end: null } );
				return;
			}
			var intervals = [];
			( data.spans || [] ).forEach( function ( span ) {
				var ranges = Array.isArray( span.token_ranges ) ? span.token_ranges.map( function ( range ) { return { start: range[ 0 ], end: range[ 1 ] }; } ) : [ { start: span.start, end: span.end } ];
				ranges.forEach( function ( range ) {
					var start = Math.max( fragment.start, range.start );
					var end = Math.min( fragment.end, range.end );
					if ( start < end ) {
						intervals.push( { start: start, end: end, revisionId: String( span.revision_id ) } );
					}
				} );
			} );
			intervals.sort( function ( left, right ) { return left.start - right.start || left.end - right.end; } );
			var cursor = fragment.start;
			intervals.forEach( function ( interval ) {
				if ( interval.start > cursor ) {
					parts.push( { text: fragment.text.slice( cursor - fragment.start, interval.start - fragment.start ), revisionId: null, start: cursor, end: interval.start } );
				}
				var start = Math.max( cursor, interval.start );
				if ( start >= interval.end ) {
					return;
				}
				var text = fragment.text.slice( start - fragment.start, interval.end - fragment.start );
				parts.push( { text: text, revisionId: /\S/u.test( text ) ? interval.revisionId : null, start: start, end: interval.end } );
				cursor = interval.end;
			} );
			if ( cursor < fragment.end ) {
				parts.push( { text: fragment.text.slice( cursor - fragment.start ), revisionId: null, start: cursor, end: fragment.end } );
			}
		} );
		var quote = selection.exactText || '';
		var quoteCursor = 0;
		for ( var i = 0; i < parts.length; i++ ) {
			var position = quote.indexOf( parts[ i ].text, quoteCursor );
			if ( position < 0 ) {
				return [];
			}
			parts[ i ].quoteStart = position;
			parts[ i ].quoteEnd = position + parts[ i ].text.length;
			quoteCursor = parts[ i ].quoteEnd;
		}
		return parts;
	}

	function revisionGroups( quote, parts, data ) {
		var groups = new Map();
		var activeSegment = null;
		parts.forEach( function ( part ) {
			if ( !part.revisionId || !/\S/u.test( part.text ) ) {
				if ( /\S/u.test( part.text ) ) {
					activeSegment = null;
				}
				return;
			}
			var id = String( part.revisionId );
			var group = groups.get( id );
			if ( !group ) {
				group = { revisionId: id, ranges: [], snippets: [], revision: H.revisionIndex( data ).get( id ) };
				groups.set( id, group );
			}
			group.ranges.push( { start: part.start, end: part.end } );
			if ( activeSegment && activeSegment.revisionId === id && !/\S/u.test( quote.slice( activeSegment.end, part.quoteStart ) ) ) {
				activeSegment.end = part.quoteEnd;
			} else {
				activeSegment = { revisionId: id, start: part.quoteStart, end: part.quoteEnd };
				group.snippets.push( activeSegment );
			}
		} );
		groups.forEach( function ( group ) {
			group.snippets.forEach( function ( snippet ) { snippet.text = quote.slice( snippet.start, snippet.end ); } );
		} );
		return Array.from( groups.values() );
	}

	function tokenIdsForRanges( data, ranges ) {
		var tokenIds = new Set();
		( data.spans || [] ).forEach( function ( span ) {
			var selectedRanges = ranges.filter( function ( range ) { return span.start < range.end && span.end > range.start; } );
			if ( !selectedRanges.length ) {
				return;
			}
			if ( Array.isArray( span.token_ranges ) ) {
				var ownIds = new Set( span.token_ranges.map( function ( range ) { return String( range[ 2 ] ); } ) );
				var selectedOwnIds = new Set();
				span.token_ranges.forEach( function ( tokenRange ) {
					if ( ranges.some( function ( range ) { return tokenRange[ 0 ] < range.end && tokenRange[ 1 ] > range.start; } ) ) {
						selectedOwnIds.add( String( tokenRange[ 2 ] ) );
					}
				} );
				selectedOwnIds.forEach( function ( id ) { tokenIds.add( id ); } );
				if ( !selectedOwnIds.size ) {
					return;
				}
				( span.lineage_ids || [] ).forEach( function ( id ) {
					if ( !ownIds.has( String( id ) ) ) {
						tokenIds.add( String( id ) );
					}
				} );
			} else {
				tokenIds.add( String( span.token_id ) );
				( span.lineage_ids || [] ).forEach( function ( id ) { tokenIds.add( String( id ) ); } );
			}
		} );
		return tokenIds;
	}

	function eventsForTokenIds( events, tokenIds ) {
		return ( events || [] ).filter( function ( event ) {
			var tokenMatch = ( event.token_ids || [] ).some( function ( id ) { return tokenIds.has( String( id ) ); } );
			var boundaryChange = typeof event.before === 'string' && event.before.length > 0 &&
				( tokenIds.has( String( event.left_token_id || '' ) ) || tokenIds.has( String( event.right_token_id || '' ) ) );
			return tokenMatch || boundaryChange;
		} );
	}

	function nearestStatement( selection ) {
		if ( !selection || !selection.rangeCount ) {
			return null;
		}
		var lastStatement = null;
		for ( var index = 0; index < selection.rangeCount; index++ ) {
			var range = selection.getRangeAt( index );
			var walker = document.createTreeWalker( article || range.commonAncestorContainer, NodeFilter.SHOW_TEXT );
			var textNode;
			while ( ( textNode = walker.nextNode() ) ) {
				if ( root.contains( textNode ) || !range.intersectsNode( textNode ) ) {
					continue;
				}
				var selectedPart = document.createRange();
				selectedPart.selectNodeContents( textNode );
				if ( range.compareBoundaryPoints( Range.START_TO_START, selectedPart ) > 0 ) {
					selectedPart.setStart( range.startContainer, range.startOffset );
				}
				if ( range.compareBoundaryPoints( Range.END_TO_END, selectedPart ) < 0 ) {
					selectedPart.setEnd( range.endContainer, range.endOffset );
				}
				if ( selectedPart.toString() ) {
					var statement = textNode.parentElement && textNode.parentElement.closest( 'p, li, blockquote, h1, h2, h3, h4, h5, h6, dt, dd, figcaption' );
					if ( statement ) {
						lastStatement = statement;
					}
				}
			}
		}
		return lastStatement;
	}

	function placeInline( statement ) {
		if ( !statement || !statement.parentNode ) {
			currentHost = root;
			return;
		}
		if ( currentHost !== root && currentHost.parentNode ) {
			currentHost.remove();
		}
		statement.parentNode.insertBefore( root, statement.nextSibling );
		currentHost = root;
	}

	function restoreRootPosition() {
		if ( originalRootParent && originalRootParent.isConnected && !( article && ( originalRootParent === article || article.contains( originalRootParent ) ) ) ) {
			var reference = originalRootNextSibling && originalRootNextSibling.parentNode === originalRootParent ? originalRootNextSibling : null;
			originalRootParent.insertBefore( root, reference );
		} else if ( article && article.parentNode ) {
			article.parentNode.insertBefore( root, article.nextSibling );
		}
		currentHost = root;
	}

	function openBreakdown( data, selection ) {
		placeInline( selection.statement || nearestStatement( window.getSelection() ) );
		buildActionBar();
		addLatestButton();
		var panel = element( 'section', 'pb-breakdown' );
		panel.setAttribute( 'aria-labelledby', 'pb-breakdown-title' );
		var header = element( 'div', 'pb-breakdown-header' );
		var heading = element( 'h2', '', 'Wording history' );
		heading.id = 'pb-breakdown-title';
		header.appendChild( heading );
		var close = element( 'button', 'pb-button pb-close', 'Close history' );
		close.type = 'button';
		close.addEventListener( 'click', function () {
			closeBreakdown( panel );
		} );
		header.appendChild( close );
		panel.appendChild( header );
		var quote = element( 'blockquote', 'pb-selected-text', selectedText || selection.exactText || 'Selected wording unavailable' );
		var quoteParts = selectedQuoteParts( data, selection );
		var groups = revisionGroups( selection.exactText || '', quoteParts, data );
		var context = { panel: panel, quote: quote, data: data, selection: selection, groups: groups };
		renderSelectedQuote( quote, context, quoteParts );
		panel.appendChild( quote );
		var rangeNote = ( selection.unmapped || [] ).length;
		if ( rangeNote ) {
			panel.appendChild( element( 'p', 'pb-warning', selection.unmapped.map( function ( item ) { return item.reason; } ).join( ' ' ) ) );
		}
		appendRevisionGroups( panel, context );
		appendTimeline( panel, data, selection );
		root.appendChild( panel );
		buildDateForm();
		close.focus();
	}

	function renderSelectedQuote( quote, context, parts ) {
		var exactText = context.selection.exactText || '';
		quote.replaceChildren();
		if ( !parts.length ) {
			quote.textContent = exactText;
			return;
		}
		var cursor = 0;
		parts.forEach( function ( part ) {
			if ( part.quoteStart < cursor ) {
				return;
			}
			if ( part.quoteStart > cursor ) {
				quote.appendChild( document.createTextNode( exactText.slice( cursor, part.quoteStart ) ) );
			}
			if ( part.revisionId && /\S/u.test( part.text ) ) {
				var phrase = element( 'span', 'pb-selection-phrase', part.text );
				phrase.dataset.pbRevisionId = part.revisionId;
				phrase.dataset.pbStart = String( part.start );
				phrase.dataset.pbEnd = String( part.end );
				applyRevisionColor( phrase, part.revisionId );
				phrase.tabIndex = 0;
				phrase.setAttribute( 'role', 'button' );
				phrase.setAttribute( 'aria-label', 'Focus history for revision ' + part.revisionId + ': ' + part.text );
				phrase.addEventListener( 'click', function () { focusRevisionHistory( part.revisionId, context, [ { start: part.start, end: part.end } ] ); } );
				phrase.addEventListener( 'keydown', function ( event ) {
					if ( event.key === 'Enter' || event.key === ' ' ) {
						event.preventDefault();
						focusRevisionHistory( part.revisionId, context, [ { start: part.start, end: part.end } ] );
					}
				} );
				quote.appendChild( phrase );
			} else {
				quote.appendChild( document.createTextNode( part.text ) );
			}
			cursor = part.quoteEnd;
		} );
		if ( cursor < exactText.length ) {
			quote.appendChild( document.createTextNode( exactText.slice( cursor ) ) );
		}
	}

	function appendRevisionGroups( panel, context ) {
		var section = element( 'section', 'pb-contributors' );
		section.appendChild( element( 'h3', '', 'Selected wording by revision' ) );
		if ( !context.groups.length ) {
			section.appendChild( element( 'p', 'pb-warning', 'No verified revision owner is available for the selected visible wording.' ) );
			panel.appendChild( section );
			return;
		}
		context.groupSection = section;
		context.groups.forEach( function ( group ) {
			var groupNode = element( 'section', 'pb-revision-group' );
			groupNode.dataset.pbRevisionId = group.revisionId;
			applyRevisionColor( groupNode, group.revisionId );
			var revision = group.revision;
			var who = revision && revision.user || 'Identity unavailable';
			var trigger = element( 'button', 'pb-revision-group-focus', 'Revision ' + group.revisionId + ' · ' + who + ' · ' + formatUtc( revision && revision.timestamp ) );
			trigger.type = 'button';
			trigger.addEventListener( 'click', function () { focusRevisionHistory( group.revisionId, context ); } );
			groupNode.appendChild( trigger );
			var snippets = element( 'ul', 'pb-group-snippets' );
			group.snippets.forEach( function ( snippet ) {
				snippets.appendChild( element( 'li', 'pb-group-snippet', snippet.text ) );
			} );
			groupNode.appendChild( snippets );
			if ( revision && revision.comment ) {
				groupNode.appendChild( element( 'p', 'pb-summary', 'Edit summary: ' + revision.comment ) );
			}
			if ( revision ) {
				groupNode.appendChild( revisionActions( revision ) );
			}
			section.appendChild( groupNode );
		} );
		section.appendChild( element( 'p', 'pb-muted', 'Last changed identifies the revision that changed the present wording; it does not prove who first introduced the idea.' ) );
		panel.appendChild( section );
	}

	function focusRevisionHistory( revisionId, context, selectedRanges ) {
		var id = revisionId === null ? null : String( revisionId );
		context.quote.querySelectorAll( '.pb-selection-phrase' ).forEach( function ( phrase ) {
			var intersects = selectedRanges && selectedRanges.some( function ( range ) {
				return Number( phrase.dataset.pbStart ) < range.end && Number( phrase.dataset.pbEnd ) > range.start;
			} );
			phrase.classList.toggle( 'is-focused', id !== null && phrase.dataset.pbRevisionId === id && ( !selectedRanges || intersects ) );
		} );
		context.groupSection.querySelectorAll( '.pb-revision-group' ).forEach( function ( group ) {
			group.classList.toggle( 'is-focused', id !== null && group.dataset.pbRevisionId === id );
		} );
		var existingAction = context.panel.querySelector( '.pb-focused-history' );
		if ( existingAction ) {
			existingAction.remove();
		}
		var existingTimeline = context.panel.querySelector( '.pb-timeline' );
		if ( existingTimeline ) {
			existingTimeline.remove();
		}
		if ( id === null ) {
			appendTimeline( context.panel, context.data, context.selection );
			return;
		}
		var group = context.groups.find( function ( item ) { return item.revisionId === id; } );
		if ( !group ) {
			return;
		}
		var focusRanges = selectedRanges || group.ranges;
		var tokenIds = tokenIdsForRanges( context.data, focusRanges );
		var allEvents = context.selection && Array.isArray( context.selection.events ) ? context.selection.events : context.data.selection && context.data.selection.events || [];
		var focusedSelection = Object.assign( {}, context.selection, {
			ranges: focusRanges,
			revision_ids: [ Number( id ) ],
			events: eventsForTokenIds( allEvents, tokenIds )
		} );
		var action = element( 'div', 'pb-focused-history' );
		var showFull = element( 'button', 'pb-button', 'Show full selection' );
		showFull.type = 'button';
		showFull.addEventListener( 'click', function () { focusRevisionHistory( null, context ); } );
		action.appendChild( showFull );
		context.groupSection.after( action );
		appendTimeline( context.panel, context.data, focusedSelection );
	}

	function closeBreakdown( panel ) {
		if ( !panel || !panel.isConnected ) {
			return;
		}
		panel.remove();
		restoreRootPosition();
		renderFull( currentData );
		var focusTarget = resolveReturnFocus();
		returnFocus = null;
		returnFocusAnchor = null;
		if ( focusTarget ) {
			focusTarget.focus();
		}
	}

	document.addEventListener( 'keydown', function ( event ) {
		if ( event.key !== 'Escape' ) {
			return;
		}
		var panel = root.querySelector( '.pb-breakdown' );
		if ( !panel ) {
			return;
		}
		event.preventDefault();
		closeBreakdown( panel );
	} );

	function appendContributors( panel, data ) {
		var section = element( 'section', 'pb-contributors' );
		section.appendChild( element( 'h3', '', 'Contributions to this selection' ) );
		var ids = new Set( data.selection && Array.isArray( data.selection.revision_ids ) ? data.selection.revision_ids.map( String ) : [] );
		var revisions = H.revisionIndex( data );
		if ( !ids.size ) {
			section.appendChild( element( 'p', 'pb-warning', data.selection ? 'No verified contributor mapping is available for this selection.' : 'The service did not return contributor details specific to this selection.' ) );
		} else {
			var list = element( 'ul', 'pb-contributor-list' );
			ids.forEach( function ( id ) {
				var revision = revisions.get( id );
				var item = element( 'li', 'pb-contributor' );
				if ( !revision ) {
					item.textContent = 'Revision ' + id + ' — details unavailable';
				} else {
					var identity = revision.user || 'Identity unavailable';
					var source = revision.source ? 'Imported from ' + revision.source.wiki + ' (source page ' + revision.source.page_id + ', source revision ' + revision.source.revision_id + '; local revision ' + id + '). The local import account is mapped provenance, not independent authentication of the source account.' : 'Local revision ' + id;
					item.appendChild( element( 'strong', '', identity ) );
					item.appendChild( element( 'span', '', ' · ' + formatUtc( revision.timestamp ) + ' · ' + source ) );
					if ( revision.comment ) {
						item.appendChild( element( 'p', 'pb-summary', 'Edit summary: ' + revision.comment ) );
					}
					var actions = revisionActions( revision );
					if ( actions.childNodes.length ) {
						item.appendChild( actions );
					}
				}
				list.appendChild( item );
			} );
			section.appendChild( list );
		}
		section.appendChild( element( 'p', 'pb-muted', 'Last changed identifies the revision that changed the present wording; it does not prove who first introduced the idea.' ) );
		panel.appendChild( section );
	}

	function appendTimeline( panel, data, selection ) {
		var section = element( 'section', 'pb-timeline' );
		section.appendChild( element( 'h3', '', 'Introductions, replacements and removals' ) );
		var selectedEvents = selection && Array.isArray( selection.events ) ? selection.events : data.selection && Array.isArray( data.selection.events ) ? data.selection.events : null;
		var events = selection ? selectedEvents : data.events || [];
		if ( events === null ) {
			section.appendChild( element( 'p', 'pb-warning', 'The service did not return history specific to this selection, so unrelated page edits are not shown.' ) );
			panel.appendChild( section );
			return;
		}
		if ( !events.length ) {
			section.appendChild( element( 'p', 'pb-muted', 'No verified wording changes were returned for this selection.' ) );
			panel.appendChild( section );
			return;
		}
		var revisions = H.revisionIndex( data );
		events.forEach( function ( change ) {
			var details = element( 'details', 'pb-event' );
			details.dataset.pbRevisionId = String( change.revision_id );
			applyRevisionColor( details, change.revision_id );
			var revision = revisions.get( String( change.revision_id ) );
			var description = revision ? formatUtc( revision.timestamp ) + ' · ' + ( revision.user || 'Identity unavailable' ) : 'Revision ' + change.revision_id;
			if ( change.ambiguous ) {
				description += ' · lineage uncertain';
			}
			details.appendChild( element( 'summary', '', description ) );
			if ( change.before ) {
				var before = element( 'p', 'pb-before' );
				before.appendChild( element( 'strong', '', 'Before: ' ) );
				before.appendChild( document.createTextNode( change.before ) );
				details.appendChild( before );
			} else {
				details.appendChild( element( 'p', 'pb-before', 'Before: no text in the selected lineage.' ) );
			}
			if ( change.after ) {
				var after = element( 'p', 'pb-after' );
				after.appendChild( element( 'strong', '', 'After: ' ) );
				after.appendChild( document.createTextNode( change.after ) );
				details.appendChild( after );
			} else {
				details.appendChild( element( 'p', 'pb-after', 'After: wording was removed.' ) );
			}
			if ( change.ambiguous ) {
				details.appendChild( element( 'p', 'pb-warning', change.reason || 'The revision history does not establish one unique text lineage.' ) );
			}
			if ( revision && revision.comment ) {
				details.appendChild( element( 'p', 'pb-summary', 'Edit summary: ' + revision.comment ) );
			}
			if ( revision ) {
				details.appendChild( revisionActions( revision ) );
			}
			section.appendChild( details );
		} );
		panel.appendChild( section );
	}

	function revisionActions( revision ) {
		var actions = element( 'div', 'pb-links' );
		[ [ 'Compare with previous revision', revision.diff_url ], [ 'View editor’s changes', revision.contributions_url ], [ 'Open this revision', revision.url ] ].forEach( function ( entry ) {
			var anchor = link( entry[ 0 ], entry[ 1 ] );
			if ( anchor ) {
				actions.appendChild( anchor );
			}
		} );
		if ( revision.source && revision.source.url ) {
			var source = link( 'Source revision ' + revision.source.revision_id, revision.source.url );
			if ( source ) {
				actions.appendChild( source );
			}
		}
		return actions;
	}

	function formatUtc( value ) {
		if ( !value ) {
			return 'Time unavailable';
		}
		var date = new Date( value );
		return Number.isNaN( date.getTime() ) ? 'Time unavailable' : new Intl.DateTimeFormat( undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' } ).format( date ) + ' UTC';
	}

	function coverageSummary( data ) {
		var coverage = data.coverage || {};
		var summary = element( 'div', 'pb-coverage' );
		var status = coverage.history_complete ? 'History coverage complete for the available source.' : 'History coverage is incomplete.';
		summary.appendChild( element( 'p', '', status ) );
		if ( coverage.source_anchor_timestamp ) {
			summary.appendChild( element( 'p', '', 'Imported source anchor: ' + formatUtc( coverage.source_anchor_timestamp ) + ' (source revision ' + coverage.source_anchor_revision_id + ').' ) );
		}
		if ( coverage.latest_timestamp && coverage.source_anchor_timestamp && coverage.latest_timestamp !== coverage.source_anchor_timestamp ) {
			summary.appendChild( element( 'p', '', 'Latest local revision: ' + formatUtc( coverage.latest_timestamp ) + '. This may differ from the imported source anchor.' ) );
		}
		if ( coverage.earliest_timestamp || coverage.latest_timestamp ) {
			summary.appendChild( element( 'p', '', 'Available history: ' + formatUtc( coverage.earliest_timestamp ) + ' to ' + formatUtc( coverage.latest_timestamp ) + '.' ) );
		}
		if ( coverage.source_anchor_timestamp && data.snapshot && Date.parse( data.snapshot.timestamp ) > Date.parse( coverage.source_anchor_timestamp ) ) {
			summary.appendChild( element( 'p', 'pb-warning', 'This local snapshot is later than the imported source cutoff; it does not establish the live source wiki’s state at that time.' ) );
		}
		( coverage.reasons || [] ).forEach( function ( reason ) {
			summary.appendChild( element( 'p', 'pb-warning', reason ) );
		} );
		return summary;
	}

	function renderCoverage( data ) {
		if ( !root.querySelector( '.pb-action-bar' ) ) {
			buildActionBar();
			return;
		}
		var old = root.querySelector( '.pb-coverage' );
		if ( old ) {
			old.remove();
		}
		root.appendChild( coverageSummary( data ) );
		legend( root, data );
	}

	function legend( parent, data ) {
		var old = parent.querySelector( ':scope > .pb-legend' );
		if ( old ) {
			old.remove();
		}
		var box = element( 'section', 'pb-legend' );
		box.setAttribute( 'aria-labelledby', 'pb-legend-title' );
		var heading = element( 'h3', '', 'Revision colour key' );
		heading.id = 'pb-legend-title';
		box.appendChild( heading );
		box.appendChild( element( 'p', '', 'Each fill identifies the last-changing revision, not editor identity or claim validity. Colours can repeat in long histories; revision IDs stay visible. Select a coloured passage to inspect its wording history.' ) );
		var entries = new Map();
		( data.spans || [] ).forEach( function ( span ) {
			entries.set( String( span.revision_id ), ( entries.get( String( span.revision_id ) ) || 0 ) + 1 );
		} );
		var revisions = H.revisionIndex( data );
		if ( entries.size ) {
			var list = element( 'ul', 'pb-legend-list' );
			entries.forEach( function ( count, id ) {
				var revision = revisions.get( id );
				var item = element( 'li', '' );
				var inspect = element( 'button', 'pb-revision-legend', '' );
				inspect.type = 'button';
				inspect.setAttribute( 'aria-label', 'Focus history for revision ' + id + ': ' + ( revision && revision.user || 'Identity unavailable' ) );
				var swatch = element( 'span', 'pb-color-swatch' );
				applyRevisionColor( swatch, id );
				inspect.appendChild( swatch );
				inspect.appendChild( document.createTextNode( ( revision && revision.user || 'Identity unavailable' ) + ' · ' + formatUtc( revision && revision.timestamp ) + ' · revision ' + id + ' · ' + count + ' mapped passage' + ( count === 1 ? '' : 's' ) ) );
				inspect.addEventListener( 'click', function () {
					var attributed = Array.from( article.querySelectorAll( '.pb-attributed[data-pb-revision-id]' ) ).find( function ( node ) { return node.dataset.pbRevisionId === id; } );
					if ( attributed ) {
						attributed.focus();
						attributed.click();
					}
				} );
				item.appendChild( inspect );
				list.appendChild( item );
			} );
			box.appendChild( list );
		}
		parent.appendChild( box );
	}

	function buildDateForm() {
		var section = element( 'section', 'pb-date-query' );
		section.appendChild( element( 'h2', '', 'Find a version by date' ) );
		section.appendChild( element( 'p', 'pb-muted', 'Examples: “As of 15 March 2026”, “Between 1 February and 31 March 2026”, or “Latest version before 1 April 2026”. Dates and times are interpreted in UTC.' ) );
		var natural = element( 'input', 'pb-date-natural' );
		natural.type = 'text';
		natural.placeholder = 'As of 15 March 2026';
		natural.setAttribute( 'aria-label', 'Describe a date query' );
		var naturalButton = element( 'button', 'pb-button', 'Interpret date query' );
		naturalButton.type = 'button';
		var manual = element( 'details', 'pb-manual-date' );
		manual.appendChild( element( 'summary', '', 'Use manual UTC date and time' ) );
		var mode = element( 'select', 'pb-date-mode' );
		[ [ 'asof', 'As of (inclusive)' ], [ 'before', 'Strictly before' ], [ 'range', 'Between (inclusive)' ] ].forEach( function ( pair ) {
			var option = element( 'option', '', pair[ 1 ] );
			option.value = pair[ 0 ];
			mode.appendChild( option );
		} );
		var from = element( 'input', 'pb-date-from' );
		from.type = 'datetime-local';
		from.setAttribute( 'aria-label', 'Start date and time in UTC' );
		var to = element( 'input', 'pb-date-to' );
		to.type = 'datetime-local';
		to.setAttribute( 'aria-label', 'End date and time in UTC' );
		mode.id = 'pb-date-mode';
		from.id = 'pb-date-from';
		to.id = 'pb-date-to';
		var manualButton = element( 'button', 'pb-button', 'Interpret manual bounds' );
		manualButton.type = 'button';
		var preview = element( 'div', 'pb-date-preview' );
		preview.setAttribute( 'aria-live', 'polite' );
		var results = element( 'div', 'pb-version-results' );
		naturalButton.addEventListener( 'click', function () {
			try {
				showDatePreview( section, preview, H.interpretDateQuery( natural.value ), results );
			} catch ( error ) {
				showDateError( preview, error.message );
			}
		} );
		manualButton.addEventListener( 'click', function () {
			try {
				showDatePreview( section, preview, H.manualDateQuery( mode.value, from.value, to.value ), results );
			} catch ( error ) {
				showDateError( preview, error.message );
			}
		} );
		section.append( natural, naturalButton, manual );
		var modeLabel = element( 'label', '', 'Selection rule' );
		modeLabel.htmlFor = mode.id;
		var fromLabel = element( 'label', '', 'Start date and time (UTC)' );
		fromLabel.htmlFor = from.id;
		var toLabel = element( 'label', '', 'Date and time bound (UTC)' );
		toLabel.htmlFor = to.id;
		manual.append( modeLabel, mode, fromLabel, from, toLabel, to, manualButton );
		function updateManualLabels() {
			var isRange = mode.value === 'range';
			fromLabel.hidden = !isRange;
			from.hidden = !isRange;
			toLabel.textContent = isRange ? 'End date and time (UTC)' : 'Date and time bound (UTC)';
		}
		mode.addEventListener( 'change', updateManualLabels );
		updateManualLabels();
		section.append( preview, results );
		root.appendChild( section );
	}

	function showIncompleteSelection( selection, message ) {
		restoreRootPosition();
		buildActionBar();
		root.setAttribute( 'data-state', 'incomplete' );
		root.appendChild( element( 'blockquote', 'pb-selected-text', selection.exactText || 'Selected wording unavailable' ) );
		var warning = element( 'p', 'pb-warning pb-selection-incomplete', message || 'Some selected visible text has no verified source mapping. No partial attribution was requested; select a passage whose full visible text has verified source offsets.' );
		warning.setAttribute( 'role', 'alert' );
		root.appendChild( warning );
		buildDateForm();
		addLatestButton();
	}

	function showDateError( preview, message ) {
		preview.replaceChildren( element( 'p', 'pb-error', message ) );
	}

	function showDatePreview( section, preview, query, results ) {
		preview.replaceChildren();
		var text = query.mode === 'range' ? 'From ' + query.from + ' through ' + query.to + ' UTC. ' + query.rule : 'Bound: ' + query.to + ' UTC. ' + query.rule;
		preview.appendChild( element( 'p', '', text ) );
		var cutoff = sourceCutoffNotice( currentData && currentData.coverage, query );
		if ( cutoff ) {
			preview.appendChild( element( 'p', 'pb-warning', cutoff ) );
		}
		var apply = element( 'button', 'pb-button pb-primary', 'Apply these bounds' );
		apply.type = 'button';
		apply.addEventListener( 'click', function () {
			requestVersions( query, results );
		} );
		preview.appendChild( apply );
	}

	function sourceCutoffNotice( coverage, query ) {
		if ( !coverage || !coverage.source_anchor_timestamp || !query || !query.to ) {
			return null;
		}
		var anchor = Date.parse( coverage.source_anchor_timestamp );
		var bound = Date.parse( query.to );
		if ( !Number.isFinite( anchor ) || !Number.isFinite( bound ) || bound <= anchor ) {
			return null;
		}
		return 'These bounds extend past imported source coverage ending ' + formatUtc( coverage.source_anchor_timestamp ) + '. Only available local revisions are listed; the latest matching result does not prove the live source wiki’s state at the requested date.';
	}

	function requestVersions( query, results, cursor, append ) {
		var request = beginRequest();
		if ( !append ) {
			results.replaceChildren( element( 'p', 'pb-status', 'Finding matching revisions…' ) );
		} else {
			var more = results.querySelector( '.pb-version-more' );
			if ( more ) {
				more.remove();
			}
			results.appendChild( element( 'p', 'pb-status', 'Loading more revisions…' ) );
		}
		var params = { op: 'versions', mode: query.mode, to: query.to, limit: 100 };
		if ( query.from ) {
			params.from = query.from;
		}
		if ( cursor ) {
			params.cursor = cursor;
		}
		apiRequest( params, 'GET', request.signal ).then( function ( response ) {
			if ( !isCurrent( request ) ) {
				return;
			}
			if ( response.status !== 'ready' ) {
				throw new Error( response.reason || 'No matching revision is available.' );
			}
			renderVersions( response, results, append, query );
		} ).catch( function ( error ) {
			if ( isCurrent( request ) && error.name !== 'AbortError' ) {
				results.replaceChildren( element( 'p', 'pb-error', error.message ) );
			}
		} );
	}

	function versionIdentityLabel( revision ) {
		var sourceUser = revision.source_user || revision.source && revision.source.user;
		var snapshot = revision.source_snapshot;
		var snapshotId = snapshot && typeof snapshot === 'object' ? snapshot.revision_id || snapshot.id : revision.source_snapshot_revision_id;
		if ( sourceUser ) {
			return 'Source editor: ' + sourceUser + ( snapshotId ? ' · source snapshot ' + snapshotId : snapshot ? ' · source snapshot' : '' );
		}
		var localUser = revision.user || 'Identity unavailable';
		if ( typeof localUser === 'string' && /^Imported>/i.test( localUser ) ) {
			return 'Local import account: ' + localUser + ' · source editor unavailable in this version result';
		}
		return 'Local editor: ' + localUser;
	}

	function renderVersions( response, results, append, query ) {
		if ( append ) {
			var status = results.querySelector( '.pb-status' );
			if ( status ) {
				status.remove();
			}
		} else {
			results.replaceChildren();
		}
		if ( !append && response.coverage && response.coverage.reasons ) {
			response.coverage.reasons.forEach( function ( reason ) {
				results.appendChild( element( 'p', 'pb-warning', reason ) );
			} );
		}
		var cutoff = !append && sourceCutoffNotice( response.coverage, query );
		if ( cutoff ) {
			results.appendChild( element( 'p', 'pb-warning', cutoff ) );
		}
		if ( !response.versions || !response.versions.length ) {
			results.appendChild( element( 'p', 'pb-muted', append ? 'No more revisions match these bounds.' : 'No revision matches these bounds. No later version was substituted.' ) );
			return;
		}
		var list = append ? results.querySelector( '.pb-version-list' ) : null;
		if ( !list ) {
			list = element( 'ol', 'pb-version-list' );
			results.appendChild( list );
		}
		response.versions.forEach( function ( revision ) {
			var item = element( 'li', '' );
			var button = element( 'button', 'pb-version', formatUtc( revision.timestamp ) + ' · ' + versionIdentityLabel( revision ) + ' · revision ' + revision.revision_id );
			button.type = 'button';
			button.addEventListener( 'click', function () {
				var url = mw.util.getUrl( title, { oldid: revision.revision_id, action: 'blame' } );
				window.location.assign( url );
			} );
			item.appendChild( button );
			list.appendChild( item );
		} );
		if ( response.continuation ) {
			var moreButton = element( 'button', 'pb-button pb-version-more', 'Load more matching revisions' );
			moreButton.type = 'button';
			moreButton.addEventListener( 'click', function () {
				requestVersions( query, results, response.continuation, true );
			} );
			results.appendChild( moreButton );
		}
	}

	function addLatestButton() {
		var action = root.querySelector( '.pb-action-bar' );
		if ( !action ) {
			return;
		}
		var latest = element( 'a', 'pb-button', 'Return to latest version' );
		latest.href = mw.util.getUrl( title, { action: 'blame' } );
		action.appendChild( latest );
	}

	function renderFull( data ) {
		buildActionBar();
		buildDateForm();
		addLatestButton();
	}

	function boot() {
		if ( !title || config.wgCanonicalSpecialPageName ) {
			setState( 'error', 'Blame is available only on readable article pages.' );
			return;
		}
		if ( snapshotTargetConflict ) {
			setState( 'error', 'This Blame action is pinned to revision ' + actionRevision + ', but the page configuration identifies revision ' + configuredRevision + '. Reload the page before analyzing history.' );
			return;
		}
		startAnalysis( null );
	}

	boot();
}() );

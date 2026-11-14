( function () {
	'use strict';

	var H = window.PalimpsestBlameHelpers;
	var root = document.getElementById( 'palimpsest-blame' );
	if ( !root || !H || !window.mw || !mw.config ) {
		return;
	}

	var config = mw.config.get( [ 'wgPageName', 'wgRevisionId', 'wgArticleId', 'wgCanonicalSpecialPageName' ] );
	var title = config.wgPageName;
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
	var selectedText = '';
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
			if ( !selection.ranges.some( function ( range ) { return span.start < range.end && span.end > range.start; } ) ) {
				return;
			}
			tokenIds.add( String( span.token_id ) );
			( span.lineage_ids || [] ).forEach( function ( id ) { tokenIds.add( String( id ) ); } );
			revisionIds.add( Number( span.revision_id ) );
			ambiguous = ambiguous || span.ambiguous === true;
		} );
		var events = ( data.events || [] ).filter( function ( event ) {
			return ( event.token_ids || [] ).some( function ( id ) { return tokenIds.has( String( id ) ); } ) ||
				tokenIds.has( String( event.left_token_id || '' ) ) || tokenIds.has( String( event.right_token_id || '' ) );
		} );
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
		if ( !selectionIsInArticle( nativeSelection ) ) {
			retainedArticleSelection = null;
			return null;
		}
		var snapshot = H.selectionRanges( nativeSelection );
		snapshot.statement = nearestStatement( nativeSelection );
		retainedArticleSelection = snapshot;
		return snapshot;
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
			buildActionBar();
			root.appendChild( element( 'p', 'pb-warning', 'This selection contains more than 64 separate verified source ranges. Select a smaller passage; no partial analysis was requested.' ) );
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
			var selection = readArticleSelection() || retainedArticleSelection;
			if ( selection ) {
				selection = Object.assign( {}, selection, { ranges: selection.ranges.slice(), unmapped: selection.unmapped.slice() } );
			}
			if ( !selection || !selection.exactText ) {
				setState( 'error', 'Select text in the article first.' );
				buildActionBar();
				return;
			}
			if ( selection.ranges.length === 0 ) {
				setState( 'error', 'This selection has no verified source offsets. Try a highlighted passage.' );
				buildActionBar();
				return;
			}
			if ( selection.ranges.length > 64 ) {
				buildActionBar();
				root.appendChild( element( 'p', 'pb-warning', 'This selection contains more than 64 separate verified source ranges. Select a smaller passage; no partial analysis was requested.' ) );
				return;
			}
			selection.statement = selection.statement || nearestStatement( window.getSelection() );
			returnFocus = inspect;
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
				node.style.setProperty( '--pb-revision-hue', String( revisionHue( id ) ) );
			} else if ( revisionIds.size > 1 ) {
				node.classList.add( 'pb-mixed' );
			}
			var revision = revisionIds.size === 1 && H.revisionIndex( currentData ).get( Array.from( revisionIds )[ 0 ] );
			if ( interactive ) {
				return;
			}
			node.setAttribute( 'tabindex', '0' );
			node.setAttribute( 'role', 'button' );
			node.setAttribute( 'aria-label', 'Inspect attributed wording' + ( revision ? ' changed in revision ' + revision.revision_id + ' by ' + ( revision.user || 'an unavailable identity' ) + ' on ' + formatUtc( revision.timestamp ) : '' ) + ': ' + node.textContent );
			var activate = function () {
				var selection = readArticleSelection() || retainedArticleSelection;
				var intersects = selection && selection.ranges.some( function ( range ) { return range.end > mapping.start && range.start < mapping.end; } );
				if ( !intersects ) {
					selection = { exactText: node.textContent, ranges: [ { start: mapping.start, end: mapping.end } ], unmapped: [], statement: node.closest( 'p, li, blockquote, h1, h2, h3, h4, h5, h6, dt, dd, figcaption' ) };
				}
				returnFocus = node;
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

	function revisionHue( value ) {
		var hash = 2166136261;
		for ( var i = 0; i < value.length; i++ ) {
			hash ^= value.charCodeAt( i );
			hash = Math.imul( hash, 16777619 );
		}
		return ( hash >>> 0 ) % 360;
	}

	function nearestStatement( selection ) {
		var active = selection && selection.rangeCount ? selection.getRangeAt( 0 ).startContainer : null;
		var node = active && ( active.nodeType === 1 ? active : active.parentElement );
		return node && node.closest( 'p, li, blockquote, h1, h2, h3, h4, h5, h6, dt, dd, figcaption' );
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

	function openBreakdown( data, selection ) {
		placeInline( selection.statement || nearestStatement( window.getSelection() ) );
		buildActionBar();
		buildDateForm();
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
			panel.remove();
			renderFull( currentData );
			if ( returnFocus && returnFocus.isConnected ) {
				returnFocus.focus();
			} else {
				var inspect = root.querySelector( '.pb-action-bar button' );
				if ( inspect ) {
					inspect.focus();
				}
			}
		} );
		header.appendChild( close );
		panel.appendChild( header );
		var quote = element( 'blockquote', 'pb-selected-text', selectedText || selection.exactText || 'Selected wording unavailable' );
		panel.appendChild( quote );
		var rangeNote = ( selection.unmapped || [] ).length;
		if ( rangeNote ) {
			panel.appendChild( element( 'p', 'pb-warning', selection.unmapped.map( function ( item ) { return item.reason; } ).join( ' ' ) ) );
		}
		appendContributors( panel, data );
		appendTimeline( panel, data, selection );
		root.appendChild( panel );
		close.focus();
	}

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
		var hasSelectionEvents = data.selection && Array.isArray( data.selection.events );
		var events = selection ? ( hasSelectionEvents ? data.selection.events : null ) : data.events || [];
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
		var box = element( 'details', 'pb-legend' );
		box.appendChild( element( 'summary', '', 'Attribution highlights and limits' ) );
		box.appendChild( element( 'p', '', 'Underlined passages have a verified source range. Select or activate one to inspect its last-changing revision. This is text history, not proof that a statement is true.' ) );
		var entries = new Map();
		( data.spans || [] ).forEach( function ( span ) {
			entries.set( String( span.revision_id ), ( entries.get( String( span.revision_id ) ) || 0 ) + 1 );
		} );
		var revisions = H.revisionIndex( data );
		if ( entries.size ) {
			var list = element( 'ul', '' );
			entries.forEach( function ( count, id ) {
				var revision = revisions.get( id );
				var item = element( 'li', '' );
				var inspect = element( 'button', 'pb-revision-legend', ( revision && revision.user || 'Identity unavailable' ) + ' · ' + formatUtc( revision && revision.timestamp ) + ' · revision ' + id + ' changed ' + count + ' mapped passage' + ( count === 1 ? '' : 's' ) );
				inspect.type = 'button';
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

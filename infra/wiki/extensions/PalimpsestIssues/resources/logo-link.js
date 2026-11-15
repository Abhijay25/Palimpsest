/* Send the NeoWiki logo to the explorer home (/explore) when an explorer URL is configured. */
( function () {
	var base = mw.config.get( 'palimpsestExplorerUrl' );
	if ( !base ) {
		return;
	}
	var target = base.replace( /\/+$/, '' ) + '/explore';
	document.querySelectorAll( 'a.mw-logo, a.mw-wiki-logo, #p-logo a' ).forEach( function ( link ) {
		link.href = target;
	} );
}() );

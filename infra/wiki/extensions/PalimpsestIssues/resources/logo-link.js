/* Send the NeoWiki logo to the site root, which opens the Explore landing page. */
( function () {
	var base = mw.config.get( 'palimpsestExplorerUrl' );
	if ( !base ) {
		return;
	}
	var target = new URL( '/', base ).href;
	document.querySelectorAll( 'a.mw-logo, a.mw-wiki-logo, #p-logo a' ).forEach( function ( link ) {
		link.href = target;
	} );
}() );

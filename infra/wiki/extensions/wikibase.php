<?php
// Opt-in source-data rendering on an owned local wiki. Core remains pinned.
require_once __DIR__ . '/rendering.php';
$wikibase = palimpsestRenderingPackage( 'wikibase', '/var/www/html/extensions/Wikibase' );
wfLoadExtension( 'WikibaseRepository', $wikibase . '/extension-repo.json' );
wfLoadExtension( 'WikibaseClient', $wikibase . '/extension-client.json' );
// This mirror matches captured public sitelinks; account/review wiki identity
// remains the independent canonical-server/database identity in Issues.
$wgWBClientSettings['siteGlobalID'] = $wgLanguageCode . 'wiki';
$wgWBClientSettings['siteGroup'] = 'wikipedia';
$wgWBRepoSettings['localClientDatabases'] = [];
$wgWBRepoSettings['wikibasePingback'] = false;
// Captured source entities are changed only by the explicit maintenance import.
$wgAvailableRights[] = 'palimpsest-import-source-data';
foreach ( [ 120, 121, 122, 123 ] as $namespace ) {
    $wgNamespaceProtection[$namespace] = [ 'palimpsest-import-source-data' ];
}

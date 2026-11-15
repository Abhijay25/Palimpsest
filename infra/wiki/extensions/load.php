<?php
// Feature branch only: upstream MediaWiki core remains in its pinned image.
require_once __DIR__ . '/source-namespaces.php';
$wgExtraNamespaces ??= [];
palimpsestSourceNamespaces( '/etc/palimpsest/source-namespaces.json', getenv( 'MW_LANG' ) ?: $wgLanguageCode, $wgExtraNamespaces );
// Some source editions host article files outside Commons. Use core's real
// foreign repository, retaining file description/licensing links and caching.
if ( getenv( 'PALIMPSEST_SOURCE_MEDIA' ) === '1' ) {
    $sourceLanguage = getenv( 'MW_LANG' ) ?: $wgLanguageCode;
    if ( !in_array( $sourceLanguage, [ 'en', 'fi', 'sv' ], true ) ) {
        throw new RuntimeException( 'Unsupported source media edition.' );
    }
    $wgForeignFileRepos[] = [
        'class' => \MediaWiki\FileRepo\ForeignAPIRepo::class,
        'name' => 'palimpsest-source-' . $sourceLanguage,
        'apibase' => 'https://' . $sourceLanguage . '.wikipedia.org/w/api.php',
        'fetchDescription' => true,
        'descriptionCacheExpiry' => 3600,
        // Keep source thumbnails remote, as InstantCommons does. API metadata
        // stays cached without proxying query-bearing filenames onto NTFS.
        'fileCacheExpiry' => 0,
    ];
}
if ( getenv( 'PALIMPSEST_CLDR' ) === '1' ) {
    require_once __DIR__ . '/rendering.php';
    $cldr = palimpsestRenderingPackage( 'cldr', '/var/www/html/extensions/cldr' );
    wfLoadExtension( 'cldr', $cldr . '/extension.json' );
}
if ( getenv( 'PALIMPSEST_LST' ) === '1' ) {
    require_once __DIR__ . '/rendering.php';
    $lst = palimpsestRenderingPackage( 'lst', '/var/www/html/extensions/LabeledSectionTransclusion' );
    wfLoadExtension( 'LabeledSectionTransclusion', $lst . '/extension.json' );
}
if ( getenv( 'PALIMPSEST_GEODATA' ) === '1' ) {
    require_once __DIR__ . '/rendering.php';
    $geodata = palimpsestRenderingPackage( 'geodata', '/var/www/html/extensions/GeoData' );
    wfLoadExtension( 'GeoData', $geodata . '/extension.json' );
}
if ( getenv( 'PALIMPSEST_WIKIBASE' ) === '1' ) {
    require __DIR__ . '/wikibase.php';
}
wfLoadExtension( 'PalimpsestBlame', __DIR__ . '/PalimpsestBlame/extension.json' );
$wgPalimpsestBlameProvenanceDirectory = '/etc/palimpsest';
wfLoadExtension( 'PalimpsestFlags', __DIR__ . '/PalimpsestFlags/extension.json' );
// Empty by default: diff rendering must never wait for an audit service.
$wgPalimpsestFlagsApiUrl = getenv( 'PALIMPSEST_FLAGS_API_URL' ) ?: '';
// Vector 2022 otherwise renders a desktop-width canvas on mobile devices.
$wgVectorResponsive = true;
// Native Issues is opt-in; the independent preview stays runnable for parity.
if ( getenv( 'PALIMPSEST_ISSUES_SERVICE_URL' ) ) {
    wfLoadExtension( 'PalimpsestIssues', __DIR__ . '/PalimpsestIssues/extension.json' );
    $wgPalimpsestIssuesServiceUrl = getenv( 'PALIMPSEST_ISSUES_SERVICE_URL' );
    $wgPalimpsestIssuesSecretFile = getenv( 'PALIMPSEST_ISSUES_SECRET_FILE' ) ?: '/etc/palimpsest/issues-secret';
    $wgPalimpsestIssuesExplorerUrl = getenv( 'PALIMPSEST_ISSUES_EXPLORER_URL' ) ?: '';
}

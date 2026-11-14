<?php
// Feature branch only: upstream MediaWiki core remains in its pinned image.
wfLoadExtension( 'PalimpsestBlame', __DIR__ . '/PalimpsestBlame/extension.json' );
$wgPalimpsestBlameProvenanceDirectory = '/etc/palimpsest';
wfLoadExtension( 'PalimpsestFlags', __DIR__ . '/PalimpsestFlags/extension.json' );
// Empty by default: diff rendering must never wait for an audit service.
$wgPalimpsestFlagsApiUrl = getenv( 'PALIMPSEST_FLAGS_API_URL' ) ?: '';
// Vector 2022 otherwise renders a desktop-width canvas on mobile devices.
$wgVectorResponsive = true;

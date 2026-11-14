<?php
// Feature branch only: upstream MediaWiki core remains in its pinned image.
wfLoadExtension( 'PalimpsestBlame', __DIR__ . '/PalimpsestBlame/extension.json' );
$wgPalimpsestBlameProvenanceDirectory = '/etc/palimpsest';
// Vector 2022 otherwise renders a desktop-width canvas on mobile devices.
$wgVectorResponsive = true;

<?php
// Feature branch only: upstream MediaWiki core remains in its pinned image.
wfLoadExtension( 'PalimpsestBlame', __DIR__ . '/PalimpsestBlame/extension.json' );
$wgPalimpsestBlameProvenanceDirectory = '/etc/palimpsest';

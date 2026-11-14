<?php
require_once '/var/www/html/maintenance/Maintenance.php';

use MediaWiki\Maintenance\Maintenance;

class PalimpsestConfigureInterwiki extends Maintenance {
	public function __construct() {
		parent::__construct();
		$this->addDescription( 'Configure local language-wiki links for Palimpsest.' );
	}

	public function execute() {
		$language = getenv( 'MW_LANG' );
		$project = getenv( 'MW_PROJECT' );
		$languages = [ 'fi', 'sv', 'en' ];
		$ports = [];
		foreach ( $languages as $code ) {
			$port = getenv( 'MW_PORT_' . strtoupper( $code ) );
			if ( !$port || !ctype_digit( $port ) || (int)$port < 1 || (int)$port > 65535 ) {
				$this->fatalError( "Missing or invalid port for {$code}." );
			}
			$ports[$code] = (int)$port;
		}
		if ( !in_array( $language, $languages, true ) || !$project ) {
			$this->fatalError( 'Missing Palimpsest language or project configuration.' );
		}

		$db = $this->getDB( DB_PRIMARY );
		foreach ( $languages as $target ) {
			if ( $target === $language ) {
				continue;
			}
			$prefix = $target;
			$db->delete( 'interwiki', [ 'iw_prefix' => $prefix ], __METHOD__ );
			$db->insert( 'interwiki', [
				'iw_prefix' => $prefix,
				'iw_url' => "http://127.0.0.1:{$ports[$target]}/index.php/\$1",
				'iw_api' => "http://127.0.0.1:{$ports[$target]}/api.php",
				'iw_wikiid' => "mw_{$project}_{$target}",
				'iw_local' => 1,
				'iw_trans' => 0,
			], __METHOD__ );
		}
		$this->output( "Configured local language links for {$language}.\n" );
	}
}

$maintClass = PalimpsestConfigureInterwiki::class;
require_once RUN_MAINTENANCE_IF_MAIN;

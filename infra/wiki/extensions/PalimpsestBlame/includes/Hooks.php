<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame;

use MediaWiki\Installer\DatabaseUpdater;

final class Hooks {
	public static function onLoadExtensionSchemaUpdates( DatabaseUpdater $updater ): void {
		$type = $updater->getDB()->getType();
		$updater->addExtensionTable(
			'palimpsestblame_job',
			dirname( __DIR__ ) . "/sql/$type/palimpsestblame_job.sql"
		);
		$updater->addExtensionTable(
			'palimpsestblame_job_revision',
			dirname( __DIR__ ) . "/sql/$type/palimpsestblame_job_revision.sql"
		);
	}

}

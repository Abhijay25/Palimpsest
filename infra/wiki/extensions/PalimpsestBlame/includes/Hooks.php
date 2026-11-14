<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame;

use MediaWiki\Installer\DatabaseUpdater;
use MediaWiki\MediaWikiServices;

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

	public static function onSkinTemplateNavigation( $skin, array &$links ): void {
		$title = $skin->getTitle();
		if ( !$title || !$title->exists() || !$title->canExist() || $title->isSpecialPage() ) {
			return;
		}

		$permissionManager = MediaWikiServices::getInstance()->getPermissionManager();
		if ( !$permissionManager->userCan( 'read', $skin->getUser(), $title ) ) {
			return;
		}

		$params = [ 'action' => 'blame' ];
		$oldId = $skin->getRequest()->getVal( 'oldid' );
		if ( $oldId !== null && ctype_digit( (string)$oldId ) ) {
			$params['oldid'] = (int)$oldId;
		}
		$links['views']['blame'] = [
			'text' => wfMessage( 'palimpsestblame-action' )->text(),
			'href' => $title->getLocalURL( $params ),
		];
	}
}

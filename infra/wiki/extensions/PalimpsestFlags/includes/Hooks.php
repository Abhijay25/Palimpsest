<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestFlags;

use MediaWiki\Diff\DifferenceEngine;

final class Hooks {
	/** Load only on a real, configured two-revision diff. */
	public static function onDifferenceEngineViewHeader( $differenceEngine ): void {
		if ( !$differenceEngine instanceof DifferenceEngine ) {
			return;
		}
		$config = $differenceEngine->getConfig();
		if ( trim( (string)$config->get( 'PalimpsestFlagsApiUrl' ) ) === '' ) {
			return;
		}
		$old = $differenceEngine->getOldRevision();
		$new = $differenceEngine->getNewRevision();
		if ( !$old || !$new || !$old->getId() || !$new->getId() ) {
			return;
		}
		$out = $differenceEngine->getOutput();
		$out->addModules( [ 'ext.palimpsest.flags' ] );
		$out->addJsConfigVars( [
			'wgPalimpsestFlags' => [
				'title' => $differenceEngine->getTitle()->getPrefixedText(),
				'language' => $differenceEngine->getTitle()->getPageLanguage()->getCode(),
				'oldid' => $old->getId(),
				'diff' => $new->getId(),
			],
		] );
	}
}

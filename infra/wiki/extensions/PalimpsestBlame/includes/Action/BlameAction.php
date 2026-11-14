<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Action;

use MediaWiki\Actions\Action;
use MediaWiki\Html\Html;

final class BlameAction extends Action {
	public function getName(): string {
		return 'blame';
	}

	public function show(): void {
		$title = $this->getTitle();
		$permissionManager = \MediaWiki\MediaWikiServices::getInstance()->getPermissionManager();
		if ( !$title->exists() || !$permissionManager->userCan( 'read', $this->getUser(), $title ) ) {
			$this->getOutput()->addWikiMsg( 'noarticletext' );
			return;
		}
		$output = $this->getOutput();
		$output->setPageTitle( Html::element( 'span', [], $title->getPrefixedText() ) );

		$rawOldId = $this->getRequest()->getVal( 'oldid' );
		if ( $rawOldId !== null && ( !ctype_digit( (string)$rawOldId ) || (int)$rawOldId < 1 ) ) {
			$this->getOutput()->addWikiMsg( 'palimpsestblame-revision-unavailable' );
			return;
		}
		$requested = $rawOldId === null ? 0 : (int)$rawOldId;
		$revision = \MediaWiki\MediaWikiServices::getInstance()->getRevisionLookup()->getRevisionByTitle(
			$this->getTitle(), $requested
		);
		if ( !$revision || $revision->getPageId() !== $title->getArticleID() || $revision->isDeleted( \MediaWiki\Revision\RevisionRecord::DELETED_TEXT ) ) {
			$this->getOutput()->addWikiMsg( 'palimpsestblame-revision-unavailable' );
			return;
		}
		$output->setRevisionId( $revision->getId() );
		$output->addModules( [ 'ext.palimpsestBlame' ] );
		$output->addHTML( Html::element( 'div', [
			'id' => 'palimpsest-blame',
			'data-page' => $this->getTitle()->getPrefixedDBkey(),
			'data-revision' => (string)$revision->getId(),
		], '' ) );
	}
}

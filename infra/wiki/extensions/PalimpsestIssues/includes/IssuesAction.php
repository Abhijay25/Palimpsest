<?php
declare( strict_types = 1 );
namespace MediaWiki\Extension\PalimpsestIssues;

use MediaWiki\Actions\Action;
use MediaWiki\Html\Html;
use MediaWiki\MediaWikiServices;
use Throwable;

final class IssuesAction extends Action {
    public function getName(): string { return 'issues'; }

    public function show(): void {
        $title = $this->getTitle();
        $services = MediaWikiServices::getInstance();
        if ( !$title->exists() || !$services->getPermissionManager()->userCan( 'read', $this->getUser(), $title ) ) {
            $this->getOutput()->addWikiMsg( 'noarticletext' );
            return;
        }
        $request = $this->getRequest();
        // This is an exact reconciliation redirect to core's complete article
        // renderer. Missing imports must NEVER fall back to the current article.
        if ( $request->getVal( 'source' ) !== null ) {
            try {
                $source = $request->getVal( 'source' );
                if ( !ctype_digit( $source ) || (int)$source <= 0 ) { throw new \DomainException( 'Invalid source revision.' ); }
                $resolved = SourceMap::resolve( $title, (int)$source, $this->getUser() );
                $context = $request->getQueryValues();
                unset( $context['title'], $context['action'], $context['source'], $context['oldid'], $context['local_revision'], $context['scan'], $context['token'] );
                $context['revision'] = (string)$resolved['record']['source_revision_id'];
                $this->getOutput()->redirect( $title->getFullURL( [ 'oldid' => $resolved['revision']->getId() ] + $context ) );
            } catch ( Throwable $e ) {
                $this->getOutput()->addHTML( Html::element( 'p', [ 'class' => 'error' ], $e instanceof \DomainException ? $e->getMessage() : 'Exact source reconciliation is unavailable.' ) );
            }
            return;
        }
        $query = Hooks::selectionQuery( $request, $title );
        $output = $this->getOutput();
        $output->setPageTitle( Html::element( 'span', [], $title->getPrefixedText() . ' · Issues' ) );
        $output->addModules( 'ext.palimpsest.issues' );
        $output->addJsConfigVars( 'palimpsestIssues', [
            'title' => $title->getPrefixedText(), 'edition' => $services->getMainConfig()->get( 'LanguageCode' ),
            'query' => $query, 'articleUrl' => $title->getLocalURL(),
            'canReview' => $this->getUser()->isRegistered() && $services->getPermissionManager()->userCan( 'palimpsest-review', $this->getUser(), $title ),
            'canScan' => $this->getUser()->isRegistered() && $services->getPermissionManager()->userCan( 'palimpsest-scan', $this->getUser(), $title ),
            'explorerUrl' => $services->getMainConfig()->get( 'PalimpsestIssuesExplorerUrl' ),
        ] );
        $output->addHTML( Html::element( 'div', [ 'id' => 'palimpsest-issues', 'aria-live' => 'polite' ], 'Reading stored Issues…' ) );
    }
}

<?php
declare( strict_types = 1 );
namespace MediaWiki\Extension\PalimpsestIssues;

use MediaWiki\MediaWikiServices;

final class Hooks {
    public static function selectionQuery( $request, $title ): array {
        $query = $request->getQueryValues();
        unset( $query['title'], $query['action'], $query['scan'], $query['token'] );
        if ( !isset( $query['revision'] ) && isset( $query['oldid'] ) ) {
            $local = is_scalar( $query['oldid'] ) ? (string)$query['oldid'] : 'invalid';
            $query['local_revision'] = $local;
            try {
                $page = SourceMap::page( $title );
                $matches = array_values( array_filter( $page['revisions'], static fn ( $r ) =>
                    ctype_digit( $local ) && (int)$r['local_revision_id'] === (int)$local ) );
                if ( count( $matches ) === 1 ) {
                    $query['revision'] = (string)$matches[0]['source_revision_id'];
                    unset( $query['local_revision'] );
                }
            } catch ( \Throwable ) { /* Keep an explicit unmapped local selection. */ }
        }
        return $query;
    }

    public static function articleStyles( string $language ): array {
        return $language === 'fi' ? [ 'ext.palimpsest.issues.article.fi' ] : [];
    }

    public static function parserInit( $parser ): void {
        // A full Wikibase/ShortDescription installation owns its existing hook.
        if ( !in_array( 'shortdesc', $parser->getFunctionHooks(), true ) ) {
            $parser->setFunctionHook( 'shortdesc', [ self::class, 'shortDescription' ], \MediaWiki\Parser\Parser::SFH_NO_HASH );
        }
    }

    public static function shortDescription( $parser, $description = '', $control = '' ): string {
        // Preserve imported metadata separately; this is not a Wikibase client.
        $output = $parser->getOutput();
        $value = trim( html_entity_decode( strip_tags( $description ), ENT_QUOTES | ENT_HTML5, 'UTF-8' ) );
        if ( $value !== '' && ( $control !== 'noreplace' || !$output->getPageProperty( 'palimpsest-short-description' ) ) ) {
            $output->setPageProperty( 'palimpsest-short-description', $value );
        }
        return '';
    }

    public static function articleNotice( $output, $skin ): void {
        $title = $output->getTitle();
        if ( !$title || $title->getNamespace() !== NS_MAIN || $output->getRequest()->getVal( 'action', 'view' ) !== 'view' ) { return; }
        try {
            $page = SourceMap::page( $title );
            $local = $output->getRevisionId() ?: $title->getLatestRevID();
            $matches = array_values( array_filter( $page['revisions'], static fn ( $r ) => (int)$r['local_revision_id'] === $local ) );
            $message = count( $matches ) === 1 ? 'Imported source article body. Templates, media and structured data use the installed dependency versions.' :
                'This local article revision has no verified public-source mapping. Archived Issues retain their own exact source identities.';
            $dependencies = $page['rendering_dependencies'] ?? null;
            if ( !$dependencies || ( $dependencies['state'] ?? '' ) !== 'complete' ) {
                $message .= ' Rendering dependencies are incomplete or unverified; templates, references or layout may be missing.';
            }
            $notice = \MediaWiki\Html\Html::element( 'p', [ 'class' => 'mw-message-box mw-message-box-notice' ], $message );
            if ( count( $matches ) === 1 ) {
                $mapped = SourceMap::resolve( $title, (int)$matches[0]['source_revision_id'], $skin->getUser() );
                $language = MediaWikiServices::getInstance()->getMainConfig()->get( 'LanguageCode' );
                $output->addModuleStyles( self::articleStyles( $language ) );
                $notice .= \MediaWiki\Html\Html::rawElement( 'p', [ 'class' => 'palimpsest-source-attribution' ],
                    \MediaWiki\Html\Html::element( 'a', [ 'href' => 'https://' . $language . '.wikipedia.org/w/index.php?oldid=' . $mapped['record']['source_revision_id'], 'rel' => 'noopener' ], 'Wikipedia source and contributors' )
                );
            }
            $output->prependHTML( $notice );
        } catch ( \Throwable ) { /* Ordinary pages without a source import remain ordinary wiki pages. */ }
    }

    public static function navigation( $skin, array &$links ): void {
        $title = $skin->getTitle();
        if ( !$title || !$title->exists() || $title->getNamespace() !== NS_MAIN ||
            !MediaWikiServices::getInstance()->getPermissionManager()->userCan( 'read', $skin->getUser(), $title ) ) {
            return;
        }
        if ( isset( $links['namespaces']['main'] ) ) {
            $language = MediaWikiServices::getInstance()->getMainConfig()->get( 'LanguageCode' );
            $articleLabels = [ 'en' => 'Article', 'fi' => 'Artikkeli', 'sv' => 'Artikel' ];
            $links['namespaces']['main']['text'] = $articleLabels[$language] ?? $links['namespaces']['main']['text'];
        }
        $query = self::selectionQuery( $skin->getRequest(), $title );
        $links['views']['issues'] = [ 'text' => 'Issues',
            'href' => $title->getLocalURL( [ 'action' => 'issues' ] + $query ),
            'class' => $skin->getRequest()->getVal( 'action' ) === 'issues' ? 'selected' : '' ];
        if ( $skin->getRequest()->getVal( 'action' ) === 'issues' && isset( $links['views']['view'] ) ) {
            $readQuery = $query;
            if ( isset( $query['revision'] ) && is_string( $query['revision'] ) && $query['revision'] !== '' ) {
                // Resolve even unavailable selections explicitly; never let an
                // oldid left over from another selection display another body.
                unset( $readQuery['oldid'], $readQuery['checks'], $readQuery['issue'], $readQuery['observation'], $readQuery['occurrence'] );
                $readQuery['action'] = 'issues';
                $readQuery['source'] = $query['revision'];
            }
            $links['views']['view']['href'] = $title->getLocalURL( $readQuery );
        }
    }

}

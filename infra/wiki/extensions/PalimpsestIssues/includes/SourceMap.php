<?php
declare( strict_types = 1 );
namespace MediaWiki\Extension\PalimpsestIssues;

use DomainException;
use MediaWiki\MediaWikiServices;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;

/** Read existing verified import provenance. Source IDs are NEVER local IDs. */
final class SourceMap {
    public static function canonical( $value ) {
        if ( !is_array( $value ) ) { return $value; }
        if ( !array_is_list( $value ) ) { ksort( $value, SORT_STRING ); }
        return array_map( [ self::class, 'canonical' ], $value );
    }

    public static function page( $title ): array {
        $config = MediaWikiServices::getInstance()->getMainConfig();
        $lang = $config->get( 'LanguageCode' );
        $path = rtrim( (string)$config->get( 'PalimpsestIssuesProvenanceDirectory' ), '/' ) . '/' . $lang . '.json';
        if ( !is_file( $path ) ) { throw new DomainException( 'Source import reconciliation is unavailable.' ); }
        $bundle = json_decode( file_get_contents( $path ), true, 512, JSON_THROW_ON_ERROR );
        $canonical = json_encode( self::canonical( $bundle['payload'] ?? [] ),
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR );
        if ( ( $bundle['schema_version'] ?? null ) !== 1 || ( $bundle['language'] ?? '' ) !== $lang ||
            ( $bundle['source_wiki'] ?? '' ) !== $lang . 'wiki' ||
            !hash_equals( (string)( $bundle['sha256'] ?? '' ), hash( 'sha256', $canonical ) ) ) {
            throw new DomainException( 'Source reconciliation checksum or edition is invalid.' );
        }
        $matches = array_values( array_filter( $bundle['payload']['pages'] ?? [], static fn ( $p ) =>
            ( $p['title'] ?? null ) === $title->getPrefixedText() && (int)( $p['local_page_id'] ?? 0 ) === $title->getArticleID() ) );
        if ( count( $matches ) !== 1 ) { throw new DomainException( 'This article has no unique reconciled source page.' ); }
        return $matches[0];
    }

    public static function resolve( $title, int $sourceId, $user ): array {
        $page = self::page( $title );
        $rows = array_values( array_filter( $page['revisions'] ?? [], static fn ( $r ) =>
            (int)( $r['source_revision_id'] ?? 0 ) === $sourceId ) );
        if ( count( $rows ) !== 1 || $sourceId < 1 ) {
            throw new DomainException( 'That exact source revision is not imported. No current snapshot was substituted.' );
        }
        $row = $rows[0];
        $services = MediaWikiServices::getInstance();
        $revision = $services->getRevisionLookup()->getRevisionById( (int)$row['local_revision_id'] );
        if ( !$services->getPermissionManager()->userCan( 'read', $user, $title ) || !$revision ||
            $revision->getPageId() !== $title->getArticleID() || $revision->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
            throw new DomainException( 'The reconciled local revision is not readable.' );
        }
        $content = $revision->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
        if ( !method_exists( $content, 'getText' ) ||
            !hash_equals( (string)$row['sha256'], hash( 'sha256', $content->getText() ) ) ||
            wfTimestamp( TS_ISO_8601, $revision->getTimestamp() ) !== $row['timestamp'] ||
            $revision->getParentId() !== (int)$row['local_parent_id'] ) {
            throw new DomainException( 'Source and local revision content or identity no longer match.' );
        }
        return [ 'revision' => $revision, 'record' => $row, 'page' => $page ];
    }
}

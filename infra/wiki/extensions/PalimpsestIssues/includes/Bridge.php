<?php
declare( strict_types = 1 );
namespace MediaWiki\Extension\PalimpsestIssues;

use DomainException;
use MediaWiki\MediaWikiServices;

final class Bridge {
    public static function request( $title, string $op, array $query = [], array $extra = [] ): array {
        $services = MediaWikiServices::getInstance();
        $config = $services->getMainConfig();
        $url = rtrim( (string)$config->get( 'PalimpsestIssuesServiceUrl' ), '/' );
        $secretPath = (string)$config->get( 'PalimpsestIssuesSecretFile' );
        if ( $url === '' || !is_file( $secretPath ) ) {
            throw new DomainException( 'Native Issues is not configured. No assessment was started.' );
        }
        $secret = trim( file_get_contents( $secretPath ) );
        if ( strlen( $secret ) < 32 ) { throw new DomainException( 'The Issues connection is not configured.' ); }
        $page = SourceMap::page( $title );
        $wikiId = (string)$config->get( 'PalimpsestIssuesWikiId' );
        if ( $wikiId === '' ) {
            $wikiId = hash( 'sha256', $config->get( 'Server' ) . '|' . $config->get( 'DBname' ) . '|' . $config->get( 'DBprefix' ) );
        }
        $body = json_encode( [ 'title' => $title->getPrefixedText(), 'source_page_id' => $page['source_page_id'],
            'edition' => $config->get( 'LanguageCode' ), 'wiki' => $wikiId,
            'op' => $op, 'query' => $query ] + $extra, JSON_THROW_ON_ERROR );
        $time = (string)time();
        $request = $services->getHttpRequestFactory()->create( $url . '/v1/issues', [
            'method' => 'POST', 'postData' => $body, 'timeout' => $op === 'scan' ? 180 : ( $op === 'jobplan' ? 90 : 30 ),
        ], __METHOD__ );
        $request->setHeader( 'Content-Type', 'application/json' );
        $request->setHeader( 'X-Issues-Time', $time );
        $request->setHeader( 'X-Issues-Signature', hash_hmac( 'sha256', $time . "\n" . $body, $secret ) );
        $status = $request->execute();
        $result = json_decode( $request->getContent(), true );
        if ( !$status->isOK() || !is_array( $result ) || ( $result['status'] ?? null ) !== 'ok' ) {
            throw new DomainException( is_array( $result ) && is_string( $result['error'] ?? null ) ?
                $result['error'] : 'Stored Issues are unavailable. No automatic inference or retry was started.' );
        }
        return $result['data'];
    }
}

<?php
declare( strict_types = 1 );

// Lightweight contract checks; the full mocked HttpRequestFactory suite runs in the pinned MW image.
$api = file_get_contents( __DIR__ . '/../../includes/Api/FlagsApi.php' );
function check( bool $ok, string $message ): void { if ( !$ok ) { fwrite( STDERR, "FAIL: $message\n" ); exit( 1 ); } }
check( str_contains( $api, "getMainWANObjectCache" ) && str_contains( $api, 'self::CACHE_TTL' ), 'successful results use the main WAN cache for one day' );
check( str_contains( $api, 'self::ERROR_CACHE_TTL' ), 'errors are cached briefly' );
check( str_contains( $api, 'isDeleted( RevisionRecord::DELETED_TEXT )' ), 'deleted text is refused before transmission' );
check( str_contains( $api, "'method' => 'POST'" ) && str_contains( $api, '/api/v1/audit-diff' ), 'the server calls the audit endpoint with POST' );
check( str_contains( $api, "'PalimpsestFlagsApiUrl'" ), 'unset service URL is a no-op response' );
print "PalimpsestFlags API contract checks passed\n";

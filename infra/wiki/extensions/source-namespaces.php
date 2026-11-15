<?php
/** Explicit namespace metadata for imported source pages; no core changes. */
declare( strict_types = 1 );
function palimpsestSourceNamespaces( string $path, string $language, array &$namespaces ): void {
    if ( !is_file( $path ) ) { return; }
    $data = json_decode( file_get_contents( $path ), true, 32, JSON_THROW_ON_ERROR );
    $records = $data['records'] ?? null;
    if ( ( $data['source_wiki'] ?? '' ) !== $language . 'wiki' || !is_array( $records ) || !array_is_list( $records ) ||
        !hash_equals( $data['sha256'] ?? '', hash( 'sha256', json_encode( $records, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR ) ) ) ) {
        throw new RuntimeException( 'Imported namespace metadata failed identity/integrity validation.' );
    }
    $next = $namespaces;
    foreach ( $records as $record ) {
        $id = $record['id'] ?? null; $name = $record['name'] ?? null;
        if ( !is_int( $id ) || $id < 100 || $id >= 10000 || in_array( $id, [ 828, 829 ], true ) ||
            !is_string( $name ) || $name === '' || strlen( $name ) > 255 || preg_match( '/[\[\]{}|:#<>\x00-\x20]/u', $name ) ||
            ( isset( $next[$id] ) && $next[$id] !== $name ) ) {
            throw new RuntimeException( 'Imported namespace conflicts with the native namespace configuration.' );
        }
        $next[$id] = $name;
    }
    $namespaces = $next;
}

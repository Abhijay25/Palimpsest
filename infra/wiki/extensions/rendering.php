<?php
/** Read only the prepared package metadata; startup never installs or downloads. */
function palimpsestRenderingPackage( string $component, string $directory ): string {
    $pin = json_decode( file_get_contents( __DIR__ . '/rendering.lock.json' ), true, 16, JSON_THROW_ON_ERROR )[$component];
    if ( !is_file( $directory . '/.palimpsest-rendering.json' ) || !is_file( $directory . '/gitinfo.json' ) ) {
        throw new RuntimeException( 'The prepared official rendering package is missing: ' . $component );
    }
    $prepared = json_decode( file_get_contents( $directory . '/.palimpsest-rendering.json' ), true, 16, JSON_THROW_ON_ERROR );
    $info = json_decode( file_get_contents( $directory . '/gitinfo.json' ), true, 16, JSON_THROW_ON_ERROR );
    if ( ( $prepared['commit'] ?? '' ) !== $pin['commit'] || ( $prepared['archive_sha256'] ?? '' ) !== $pin['sha256'] || trim( $info['headSHA1'] ?? '' ) !== $pin['commit'] ) {
        throw new RuntimeException( 'Prepared package does not match the rendering pin: ' . $component );
    }
    return $directory;
}

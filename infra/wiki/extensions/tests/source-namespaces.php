<?php
declare( strict_types = 1 );
require dirname( __DIR__ ) . '/source-namespaces.php';
function checkNamespace( bool $value, string $message ): void { if ( !$value ) { throw new RuntimeException( $message ); } }
function rejectsNamespace( callable $fn ): void {
    try { $fn(); } catch ( RuntimeException ) { return; }
    throw new RuntimeException( 'Invalid namespace metadata must fail.' );
}
$path = tempnam( sys_get_temp_dir(), 'namespace-contract-' );
try {
    $records = [ [ 'id' => 100, 'name' => 'Portal' ], [ 'id' => 101, 'name' => 'Portal_talk' ] ];
    $data = [ 'source_wiki' => 'enwiki', 'records' => $records, 'sha256' => hash( 'sha256', json_encode( $records ) ) ];
    file_put_contents( $path, json_encode( $data ) );
    $names = [ 200 => 'Existing' ];
    palimpsestSourceNamespaces( $path, 'en', $names );
    checkNamespace( $names === [ 200 => 'Existing', 100 => 'Portal', 101 => 'Portal_talk' ], 'Selected source namespaces must be configured without changing existing namespaces.' );
    rejectsNamespace( function () use ( $path, &$names ) { palimpsestSourceNamespaces( $path, 'fi', $names ); } );
    $collision = [ 100 => 'Existing_other_namespace' ];
    rejectsNamespace( function () use ( $path, &$collision ) { palimpsestSourceNamespaces( $path, 'en', $collision ); } );
    checkNamespace( $collision === [ 100 => 'Existing_other_namespace' ], 'Conflicts must not partly apply configuration.' );
    $data['records'][0]['id'] = 0;
    $data['sha256'] = hash( 'sha256', json_encode( $data['records'] ) );
    file_put_contents( $path, json_encode( $data ) );
    rejectsNamespace( function () use ( $path, &$names ) { palimpsestSourceNamespaces( $path, 'en', $names ); } );
    $data['records'][0]['id'] = 102;
    file_put_contents( $path, json_encode( $data ) );
    rejectsNamespace( function () use ( $path, &$names ) { palimpsestSourceNamespaces( $path, 'en', $names ); } );
    echo "Source namespace identity, integrity and collision checks passed.\n";
} finally { unlink( $path ); }

<?php
/** Explicit import of checksum-verified Wikidata captures into the local repository. */
declare( strict_types = 1 );
use MediaWiki\Maintenance\Maintenance;
use MediaWiki\User\User;
use Wikibase\Repo\WikibaseRepo;

class PalimpsestImportWikidata extends Maintenance {
    public function __construct() {
        parent::__construct();
        $this->addDescription( 'Import captured public Wikidata entities without changing existing different entities.' );
        $this->addOption( 'manifest', 'Explicit captured source manifest', true, true );
    }
    private function canonical( $value ): string {
        $sort = function ( $node ) use ( &$sort ) {
            if ( !is_array( $node ) ) { return $node; }
            if ( !array_is_list( $node ) ) { ksort( $node ); }
            return array_map( $sort, $node );
        };
        return json_encode( $sort( $value ), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR );
    }
    public function execute() {
        $path = realpath( $this->getOption( 'manifest' ) );
        if ( !$path ) { $this->fatalError( 'The selected source manifest is unavailable.' ); }
        $manifest = json_decode( file_get_contents( $path ), true, 64, JSON_THROW_ON_ERROR );
        if ( ( $manifest['source_wiki'] ?? '' ) !== 'wikidatawiki' || ( $manifest['schema_version'] ?? 0 ) !== 1 ) {
            $this->fatalError( 'Source manifest identity mismatch.' );
        }
        $deserializer = WikibaseRepo::getAllTypesEntityDeserializer();
        $serializer = WikibaseRepo::getAllTypesEntitySerializer();
        $lookup = WikibaseRepo::getEntityLookup();
        $store = WikibaseRepo::getEntityStore();
        $user = User::newSystemUser( 'Palimpsest source importer', [ 'steal' => false ] );
        if ( !$user ) { $this->fatalError( 'The source-import system account could not be created safely.' ); }
        $records = $manifest['entities']; ksort( $records ); $report = [];
        foreach ( $records as $identity => $record ) {
            if ( !preg_match( '/^[QP][1-9][0-9]*$/D', $identity ) ) { $this->fatalError( 'Invalid source entity identity.' ); }
            $file = dirname( $path ) . '/' . $identity . '.json';
            if ( is_link( $file ) || !is_file( $file ) ) { $this->fatalError( 'Source entity is unavailable or is a symbolic link.' ); }
            $raw = file_get_contents( $file );
            if ( !hash_equals( $record['sha256'], hash( 'sha256', $raw ) ) ) { $this->fatalError( 'Source entity integrity mismatch.' ); }
            $data = json_decode( $raw, true, 128, JSON_THROW_ON_ERROR );
            if ( $data['id'] !== $identity || $data['lastrevid'] !== $record['source_revision'] ) { $this->fatalError( 'Source entity revision mismatch.' ); }
            $entity = $deserializer->deserialize( $data );
            $existing = $lookup->getEntity( $entity->getId() );
            $expected = $this->canonical( $serializer->serialize( $entity ) );
            if ( $existing && $this->canonical( $serializer->serialize( $existing ) ) !== $expected ) {
                $this->fatalError( 'Existing different entity preserved: ' . $identity );
            }
            $local = null;
            if ( !$existing ) {
                $saved = $store->saveEntity( $entity, 'Imported from Wikidata source revision ' . $record['source_revision'], $user, EDIT_NEW );
                $local = $saved->getRevisionId();
            }
            $stored = $lookup->getEntity( $entity->getId() );
            if ( !$stored || $this->canonical( $serializer->serialize( $stored ) ) !== $expected ) { $this->fatalError( 'Native entity reconciliation failed: ' . $identity ); }
            $local = WikibaseRepo::getEntityRevisionLookup()->getEntityRevision( $entity->getId() )->getRevisionId();
            $report[] = [ 'id' => $identity, 'source_revision' => $record['source_revision'], 'local_revision' => $local,
                'state' => $existing ? 'already-matched' : 'imported-and-reconciled', 'source_sha256' => $record['sha256'] ];
        }
        $this->output( json_encode( [ 'source_wiki' => 'wikidatawiki', 'entities' => $report ], JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR ) . "\n" );
    }
}
return PalimpsestImportWikidata::class;

<?php
/** Source reconciliation/security contract checks. No running wiki or DB. */
declare( strict_types = 1 );
namespace MediaWiki {
    class MediaWikiServices {
        public static $test;
        public static function getInstance() { return self::$test; }
    }
}
namespace MediaWiki\Revision {
    class RevisionRecord { const DELETED_TEXT = 1; const FOR_PUBLIC = 1; }
    class SlotRecord { const MAIN = 'main'; }
}
namespace MediaWiki\Api {
    class ApiBase {
        public $request;
        public function getRequest() { return $this->request; }
    }
}
namespace Wikimedia\ParamValidator {
    class ParamValidator { const PARAM_TYPE='type'; const PARAM_DEFAULT='default'; const PARAM_REQUIRED='required'; }
}
namespace {
    use MediaWiki\MediaWikiServices;
    use MediaWiki\Extension\PalimpsestIssues\SourceMap;
    const TS_ISO_8601 = 1;
    function wfTimestamp( $format, $timestamp ) { return $timestamp; }
    require dirname( __DIR__ ) . '/includes/SourceMap.php';
    require dirname( __DIR__ ) . '/includes/IssuesApi.php';
    require dirname( __DIR__ ) . '/includes/Hooks.php';
    function check( bool $passed, string $message ): void { if ( !$passed ) { throw new \RuntimeException( $message ); } }
    function rejects( callable $fn, string $message ): void {
        try { $fn(); } catch ( \DomainException ) { return; }
        throw new \RuntimeException( $message );
    }
    $directory = sys_get_temp_dir() . '/issues-contract-' . bin2hex( random_bytes( 6 ) );
    mkdir( $directory );
    $title = new class {
        public function getPrefixedText() { return 'Winter War'; }
        public function getArticleID() { return 4; }
    };
    $revision = new class {
        public $deleted = false;
        public $text = '== Real section == Source text<ref>Reference</ref>';
        public $page = 4;
        public function getId() { return 7; }
        public function getPageId() { return $this->page; }
        public function isDeleted( $type ) { return $this->deleted; }
        public function getParentId() { return 6; }
        public function getTimestamp() { return '2025-01-01T00:00:00Z'; }
        public function getContentOrThrow( ...$args ) { return new class( $this->text ) {
            public function __construct( public $text ) {}
            public function getText() { return $this->text; }
        }; }
    };
    $config = new class( $directory ) {
        public function __construct( public $directory ) {}
        public function get( $key ) { return $key === 'LanguageCode' ? 'en' : $this->directory; }
    };
    $lookup = new class( $revision ) {
        public function __construct( public $revision ) {}
        public function getRevisionById( $id ) { return $id === 7 ? $this->revision : null; }
    };
    $pm = new class { public $allowed = true; public function userCan( ...$args ) { return $this->allowed; } };
    MediaWikiServices::$test = new class( $config, $lookup, $pm ) {
        public function __construct( public $config, public $lookup, public $pm ) {}
        public function getMainConfig() { return $this->config; }
        public function getRevisionLookup() { return $this->lookup; }
        public function getPermissionManager() { return $this->pm; }
    };
    $record = [ 'source_revision_id' => 1301539037, 'local_revision_id' => 7,
        'local_parent_id' => 6, 'timestamp' => '2025-01-01T00:00:00Z', 'sha256' => hash( 'sha256', $revision->text ) ];
    $payload = [ 'pages' => [ [ 'local_page_id' => 4, 'source_page_id' => 12, 'title' => 'Winter War',
        'history_complete' => false, 'revisions' => [ $record ] ] ] ];
    $bundle = [ 'schema_version' => 1, 'language' => 'en', 'source_wiki' => 'enwiki', 'payload' => $payload,
        'sha256' => hash( 'sha256', json_encode( SourceMap::canonical( $payload ), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) ) ];
    $path = $directory . '/en.json';
    try {
        file_put_contents( $path, json_encode( $bundle ) );
        $request = new class {
            public $query = [ 'oldid' => '7', 'scan' => '1', 'token' => 'private' ];
            public function getQueryValues() { return $this->query; }
        };
        $selection = \MediaWiki\Extension\PalimpsestIssues\Hooks::selectionQuery( $request, $title );
        check( $selection['revision'] === '1301539037' && !isset( $selection['scan'] ) && !isset( $selection['token'] ), 'Historical local selection must resolve to its source ID without scan controls.' );
        $request->query = [ 'oldid' => '8' ];
        $selection = \MediaWiki\Extension\PalimpsestIssues\Hooks::selectionQuery( $request, $title );
        check( !isset( $selection['revision'] ) && $selection['local_revision'] === '8', 'Unmapped local selection must never become a source ID or a default revision.' );
        $resolved = SourceMap::resolve( $title, 1301539037, new \stdClass );
        check( $resolved['revision']->getId() === 7, 'Must reconcile source ID to actual local ID.' );
        check( !$resolved['page']['history_complete'], 'A readable exact revision does not imply a complete import.' );
        rejects( fn () => SourceMap::resolve( $title, 7, new \stdClass ), 'A local ID is not a source ID.' );
        $revision->deleted = true;
        rejects( fn () => SourceMap::resolve( $title, 1301539037, new \stdClass ), 'Suppressed content is unavailable.' );
        $revision->deleted = false; $revision->text .= ' changed';
        rejects( fn () => SourceMap::resolve( $title, 1301539037, new \stdClass ), 'Changed local content must not inherit source evidence.' );
        $revision->text = '== Real section == Source text<ref>Reference</ref>'; $revision->page = 99;
        rejects( fn () => SourceMap::resolve( $title, 1301539037, new \stdClass ), 'Cross-page revisions must be rejected.' );
        $revision->page = 4; $pm->allowed = false;
        rejects( fn () => SourceMap::resolve( $title, 1301539037, new \stdClass ), 'Read permission is required.' );
        $pm->allowed = true; $bundle['payload']['pages'][0]['revisions'][0]['local_revision_id'] = 8;
        file_put_contents( $path, json_encode( $bundle ) );
        rejects( fn () => SourceMap::resolve( $title, 1301539037, new \stdClass ), 'Tampered reconciliation must be rejected.' );
        $api = new \MediaWiki\Extension\PalimpsestIssues\IssuesApi();
        $params = $api->getAllowedParams();
        check( $params['fresh']['type'] === [ 'yes', 'no' ] && $params['fresh']['default'] === 'no', 'Normal scans must preserve caches; boolean presence is unsafe.' );
        check( $params['reviewed']['type'] === [ 'yes', 'no' ], 'Undo must use an explicit false value, not a present boolean parameter.' );
        foreach ( [ 'list', 'detail', 'health', 'cached', 'versions', 'legacy' ] as $op ) {
            $api->request = new class( $op ) { public function __construct( public $op ) {} public function getVal( $name ) { return $this->op; } };
            check( !$api->mustBePosted() && $api->needsToken() === false, 'Read operation must not be a mutation.' );
        }
        foreach ( [ 'scan', 'review' ] as $op ) {
            $api->request = new class( $op ) { public function __construct( public $op ) {} public function getVal( $name ) { return $this->op; } };
            check( $api->mustBePosted() && $api->needsToken() === 'csrf', 'Scans/reviews require native POST/CSRF.' );
        }
        $metadata = new class {
            public $properties = [];
            public function getPageProperty( $key ) { return $this->properties[$key] ?? null; }
            public function setPageProperty( $key, $value ) { $this->properties[$key] = $value; }
        };
        $parser = new class( $metadata ) {
            public function __construct( public $output ) {}
            public function getOutput() { return $this->output; }
        };
        $hooks = \MediaWiki\Extension\PalimpsestIssues\Hooks::class;
        check( $hooks::shortDescription( $parser, '<b>Imported description</b>' ) === '', 'Description metadata must not become article text.' );
        $hooks::shortDescription( $parser, 'Replacement', 'noreplace' );
        check( $metadata->properties['palimpsest-short-description'] === 'Imported description', 'No-replace must preserve existing plain-text metadata.' );
        echo "Native source identity, visibility, integrity and mutation guards passed.\n";
    } finally { unlink( $path ); rmdir( $directory ); }
}

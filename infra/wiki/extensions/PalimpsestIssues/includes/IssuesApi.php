<?php
declare( strict_types = 1 );
namespace MediaWiki\Extension\PalimpsestIssues;

use DomainException;
use MediaWiki\Api\ApiBase;
use MediaWiki\MediaWikiServices;
use MediaWiki\Title\Title;
use Throwable;
use Wikimedia\ParamValidator\ParamValidator;

final class IssuesApi extends ApiBase {
    public function execute() {
        $params = $this->extractRequestParams();
        $title = Title::newFromText( $params['title'] );
        $services = MediaWikiServices::getInstance();
        $pm = $services->getPermissionManager();
        if ( !$title || !$title->exists() || !$pm->userCan( 'read', $this->getUser(), $title ) ) {
            $this->dieWithError( 'apierror-permissiondenied' );
        }
        $op = $params['op'];
        if ( in_array( $op, [ 'review', 'scan', 'jobplan', 'enqueue' ], true ) ) {
            $right = $op === 'review' ? 'palimpsest-review' : 'palimpsest-scan';
            if ( !$this->getUser()->isRegistered() || !$pm->userCan( $right, $this->getUser(), $title ) || $services->getReadOnlyMode()->isReadOnly() ) {
                $this->dieWithError( 'apierror-permissiondenied' );
            }
        }
        try {
            $query = json_decode( $params['selection'], true, 16, JSON_THROW_ON_ERROR );
            if ( !is_array( $query ) ) { throw new DomainException( 'Invalid evidence selection.' ); }
            $extra = [];
            if ( in_array( $op, [ 'review', 'scan', 'jobplan', 'enqueue' ], true ) ) {
                $extra = [ 'reviewer_id' => $this->getUser()->getId(), 'reviewed' => $params['reviewed'] === 'yes' ];
            }
            if ( $op === 'versions' ) {
                $page = SourceMap::page( $title );
                $result = [ 'versions' => array_map( static fn ( $r ) => [
                    'source' => $r['source_revision_id'], 'timestamp' => $r['timestamp'],
                    'local' => $r['local_revision_id'], 'source_parent' => $r['source_parent_id'] ?? null,
                ], $page['revisions'] ), 'history_complete' => (bool)( $page['history_complete'] ?? false ) ];
            } else {
                if ( in_array( $op, [ 'scan', 'cached', 'jobplan' ], true ) ) {
                    $selected = $query['revision'] ?? '';
                    if ( !ctype_digit( (string)$selected ) ) { throw new DomainException( 'Select an exact source revision.' ); }
                    $mapped = SourceMap::resolve( $title, (int)$selected, $this->getUser() );
                    $record = $mapped['record'];
                    if ( in_array( $op, [ 'scan', 'jobplan' ], true ) && $params['mode'] === 'revision' ) {
                        $parent = SourceMap::resolve( $title, (int)( $record['source_parent_id'] ?? 0 ), $this->getUser() );
                        if ( $parent['revision']->getId() !== $mapped['revision']->getParentId() ) {
                            throw new DomainException( 'The exact parent revision is not reconciled. No substitute edit was scanned.' );
                        }
                    }
                    $extra += [ 'source' => [ 'revision_id' => $record['source_revision_id'],
                        'sha256' => $record['sha256'], 'title' => $title->getPrefixedText(),
                        'timestamp' => $record['timestamp'], 'parent_id' => $record['source_parent_id'] ?? null,
                        'lang' => $services->getMainConfig()->get( 'LanguageCode' ) ],
                        'mode' => $params['mode'], 'fresh' => $params['fresh'] === 'yes' ];
                    if ( $op === 'jobplan' ) {
                        // SourceMap already verified this exact readable native
                        // content against the imported source hash. Pass it only
                        // over HMAC, avoiding an unnecessary source-site refetch.
                        $extra['source']['wikitext'] = $mapped['revision']->getContentOrThrow(
                            \MediaWiki\Revision\SlotRecord::MAIN, \MediaWiki\Revision\RevisionRecord::FOR_PUBLIC
                        )->getText();
                    }
                    if ( $op === 'jobplan' && $params['mode'] === 'revision' ) {
                        $extra['source_parent'] = [ 'revision_id' => $parent['record']['source_revision_id'],
                            'sha256' => $parent['record']['sha256'], 'title' => $title->getPrefixedText(),
                            'timestamp' => $parent['record']['timestamp'],
                            'parent_id' => $parent['record']['source_parent_id'] ?? null,
                            'lang' => $services->getMainConfig()->get( 'LanguageCode' ),
                            'wikitext' => $parent['revision']->getContentOrThrow(
                                \MediaWiki\Revision\SlotRecord::MAIN, \MediaWiki\Revision\RevisionRecord::FOR_PUBLIC
                            )->getText() ];
                    }
                }
                $result = Bridge::request( $title, $op, $query, $extra );
                if ( in_array( $op, [ 'scan', 'cached' ], true ) ) {
                    $result['native_revision'] = [ 'source' => $record['source_revision_id'],
                        'local' => $mapped['revision']->getId(), 'source_parent' => $record['source_parent_id'] ?? null,
                        'local_parent' => $mapped['revision']->getParentId(), 'timestamp' => $record['timestamp'] ];
                }
                if ( $op === 'list' ) {
                    $sourcePage = SourceMap::page( $title );
                    $result['native_import'] = [ 'history_complete' => (bool)( $sourcePage['history_complete'] ?? false ),
                        'rendering_dependencies' => $sourcePage['rendering_dependencies'] ?? [ 'state' => 'unknown' ] ];
                }
                if ( in_array( $op, [ 'scan', 'cached' ], true ) && $params['mode'] === 'page' && ( $result['status'] ?? null ) === 'ok' ) {
                    // Use the exact local revision and native parser, including
                    // imported templates/Cite/Scribunto; never the Flask reader.
                    $page = $services->getPageStore()->getPageById( $mapped['revision']->getPageId() );
                    $options = \MediaWiki\Parser\ParserOptions::newFromUser( $this->getUser() );
                    $status = $services->getParserOutputAccess()->getParserOutput( $page, $options, $mapped['revision'] );
                    if ( !$status->isOK() ) { throw new DomainException( 'The assessed revision could not be rendered. Cached evidence is preserved.' ); }
                    $parsed = $status->getValue();
                    $result['page_html'] = $parsed->getContentHolder()->getAsHtmlString();
                    $result['page_modules'] = $parsed->getModules();
                    $result['page_module_styles'] = array_values( array_unique( array_merge(
                        $parsed->getModuleStyles(), Hooks::articleStyles( $services->getMainConfig()->get( 'LanguageCode' ) )
                    ) ) );
                }
                if ( $op === 'detail' ) {
                    // Full-page source links resolve source IDs independently on
                    // each edition. No source ID is ever put directly in oldid.
                    foreach ( $result['evidence']['sources'] as &$source ) {
                        // Foreign configured links resolve independently in that wiki.
                        $source['native_url'] ??= null;
                        $url = parse_url( $source['url'] );
                        parse_str( $url['query'] ?? '', $sourceQuery );
                        if ( ( $url['host'] ?? '' ) === $services->getMainConfig()->get( 'LanguageCode' ) . '.wikipedia.org' ) {
                            try {
                                $sourceMapping = SourceMap::resolve( $title, (int)( $sourceQuery['oldid'] ?? 0 ), $this->getUser() );
                                // Fill absent presentation metadata from verified
                                // import provenance; archived evidence is unchanged.
                                if ( empty( $source['stamp'] ) ) { $source['stamp'] = $sourceMapping['record']['timestamp']; }
                                $sourceContext = $query;
                                unset( $sourceContext['source'], $sourceContext['action'], $sourceContext['title'], $sourceContext['oldid'], $sourceContext['scan'] );
                                $source['native_url'] = $title->getLocalURL( [ 'action' => 'issues', 'source' => $sourceQuery['oldid'] ] + $sourceContext );
                            } catch ( Throwable ) { $source['native_unavailable'] = 'Exact revision not reconciled locally.'; }
                        }
                    }
                    unset( $source );
                }
            }
            $this->getResult()->addValue( null, 'palimpsestissues', $result );
        } catch ( DomainException $e ) {
            $this->getResult()->addValue( null, 'palimpsestissues', [ 'status' => 'unavailable', 'error' => $e->getMessage() ] );
        } catch ( Throwable ) {
            $this->getResult()->addValue( null, 'palimpsestissues', [ 'status' => 'unavailable', 'error' => 'Stored evidence is unavailable. No inference or automatic retry was started.' ] );
        }
    }

    public function getAllowedParams() { return [
        'title' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_REQUIRED => true ],
        'op' => [ ParamValidator::PARAM_TYPE => [ 'list', 'detail', 'legacy', 'health', 'versions', 'cached', 'scan', 'review', 'translate', 'jobpolicy', 'jobplan', 'enqueue', 'jobs', 'job' ], ParamValidator::PARAM_DEFAULT => 'list' ],
        'selection' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '{}' ],
        'mode' => [ ParamValidator::PARAM_TYPE => [ 'revision', 'page', 'language' ], ParamValidator::PARAM_DEFAULT => 'revision' ],
        // MediaWiki boolean parameters mean presence, even for "false"/"0".
        // Explicit yes/no enums are required for undo and cache-preserving scans.
        'reviewed' => [ ParamValidator::PARAM_TYPE => [ 'yes', 'no' ], ParamValidator::PARAM_DEFAULT => 'no' ],
        'fresh' => [ ParamValidator::PARAM_TYPE => [ 'yes', 'no' ], ParamValidator::PARAM_DEFAULT => 'no' ],
    ]; }
    public function mustBePosted() { return in_array( $this->getRequest()->getVal( 'op' ), [ 'review', 'scan', 'translate', 'jobplan', 'enqueue' ], true ); }
    public function needsToken() { return $this->mustBePosted() ? 'csrf' : false; }
    public function isWriteMode() { return in_array( $this->getRequest()->getVal( 'op' ), [ 'review', 'scan', 'jobplan', 'enqueue' ], true ); }
}

<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Api;

use DateTimeImmutable;
use DateTimeZone;
use DomainException;
use JsonException;
use MediaWiki\Api\ApiBase;
use MediaWiki\Api\ApiMain;
use MediaWiki\Logger\LoggerFactory;
use MediaWiki\MediaWikiServices;
use MediaWiki\Parser\ParserOptions;
use MediaWiki\Parser\ParserOutput;
use MediaWiki\Page\ParserOutputAccess;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;
use MediaWiki\Title\Title;
use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionEngine;
use MediaWiki\Extension\PalimpsestBlame\Attribution\SourceTokenizer;
use MediaWiki\Extension\PalimpsestBlame\Job\BlameBuildJob;
use Throwable;
use Wikimedia\ParamValidator\ParamValidator;
use Wikimedia\ParamValidator\TypeDef\NumericDef;

final class BlameApi extends ApiBase {
	private const MAX_REVISIONS = 200;
	private const MAX_HISTORY_BYTES = 2097152;
	private const MAX_TOKENS = 200000;
	private const MAX_RESPONSE_BYTES = 2097152;

	public function __construct( ApiMain $main, string $moduleName, string $modulePrefix = '' ) {
		parent::__construct( $main, $moduleName, $modulePrefix );
	}

	public function execute() {
		$params = $this->extractRequestParams();
		$title = Title::newFromText( $params['title'] );
		if ( !$title || !$title->canExist() || !$title->exists() ) {
			$this->dieWithError( 'missingtitle' );
		}
		$services = MediaWikiServices::getInstance();
		$permissionManager = $services->getPermissionManager();
		if ( !$permissionManager->userCan( 'read', $this->getUser(), $title ) ) {
			$this->dieWithError( 'apierror-permissiondenied' );
		}

		$op = $params['op'];
		try {
			if ( $op === 'build' ) { $result = $this->createBuildJob( $title, $params ); }
			elseif ( $op === 'status' ) { $result = $this->readBuildJob( $title, $params ); }
			elseif ( $op === 'versions' ) { $result = $this->versions( $title, $params ); }
			else { $result = $this->analyze( $title, $params ); }
		} catch ( DomainException $e ) {
			$reason = $e->getMessage();
			$result = [ 'schema_version' => 1, 'status' => 'unavailable', 'reason' => $reason ];
			$target = $services->getRevisionLookup()->getRevisionByTitle( $title, $params['revision'] );
			if ( $target && $target->getPageId() === $title->getArticleID() ) {
				$result['revision_id'] = $target->getId();
			}
			$result['buildable'] = str_starts_with( $reason, 'synchronous-history-limit-exceeded;' ) && $this->canBuild( $title, $target?->getId() ?? $params['revision'] );
		} catch ( Throwable $e ) {
			LoggerFactory::getInstance( 'PalimpsestBlame' )->error( 'Request failed', [ 'exception' => $e ] );
			$this->dieWithError( 'palimpsestblame-internal-error', 'blame-internal-error', null, 500 );
		}

		if ( strlen( json_encode( $result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) ?: '' ) > self::MAX_RESPONSE_BYTES ) {
			$result = [
				'schema_version' => 1,
				'status' => 'unavailable',
				'reason' => 'response-limit-exceeded',
			];
		}
		$this->getResult()->addValue( null, 'palimpsestblame', $result );
	}

	public function getAllowedParams() {
		return [
			'op' => [ ParamValidator::PARAM_TYPE => [ 'analyze', 'versions', 'build', 'status' ], ParamValidator::PARAM_DEFAULT => 'analyze' ],
			'title' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_REQUIRED => true ],
			'revision' => [ ParamValidator::PARAM_TYPE => 'integer', NumericDef::PARAM_MIN => 0, ParamValidator::PARAM_DEFAULT => 0 ],
			'mode' => [ ParamValidator::PARAM_TYPE => [ 'asof', 'before', 'range' ], ParamValidator::PARAM_DEFAULT => 'asof' ],
			'from' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '' ],
			'to' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '' ],
			'limit' => [ ParamValidator::PARAM_TYPE => 'integer', NumericDef::PARAM_MIN => 1, NumericDef::PARAM_MAX => 100, ParamValidator::PARAM_DEFAULT => 100 ],
			'jobid' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '' ],
			'cursor' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '' ],
			'ranges' => [ ParamValidator::PARAM_TYPE => 'string', ParamValidator::PARAM_DEFAULT => '' ],
		];
	}

	public function mustBePosted() {
		return $this->getRequest()->getVal( 'op', 'analyze' ) === 'build';
	}

	public function needsToken() {
		return $this->getRequest()->getVal( 'op', 'analyze' ) === 'build' ? 'csrf' : false;
	}

	private function analyze( Title $title, array $params ): array {
		$services = MediaWikiServices::getInstance();
		$revision = $services->getRevisionLookup()->getRevisionByTitle( $title, $params['revision'] );
		if ( !$revision || $revision->getPageId() !== $title->getArticleID() ) {
			throw new DomainException( 'requested-revision-is-not-on-page' );
		}
		$db = $services->getConnectionProvider()->getPrimaryDatabase();
		$readyJobId = $db->selectField( 'palimpsestblame_job', 'pbj_id', [
			'pbj_page_id' => $revision->getPageId(),
			'pbj_revision_id' => $revision->getId(),
			'pbj_algorithm' => AttributionEngine::VERSION,
			'pbj_schema_version' => 1,
			'pbj_status' => 'ready',
		], __METHOD__ );
		if ( is_string( $readyJobId ) && $readyJobId !== '' ) {
			return $this->readBuildJob( $title, array_merge( $params, [ 'jobid' => (string)$readyJobId, 'revision' => $revision->getId() ] ) );
		}
		$history = [];
		$bytes = 0;
		$tokens = 0;
		$cursor = $revision;
		while ( $cursor && count( $history ) < self::MAX_REVISIONS ) {
			if ( $cursor->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
				throw new DomainException( 'history-contains-hidden-content' );
			}
			try {
				$content = $cursor->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
			} catch ( Throwable ) {
				throw new DomainException( 'revision-content-unavailable' );
			}
			if ( !method_exists( $content, 'getText' ) || $cursor->getMainContentModel() !== CONTENT_MODEL_WIKITEXT ) {
				throw new DomainException( 'unsupported-content-model' );
			}
			$text = $content->getText();
			$bytes += strlen( $text );
			$tokens += preg_match_all( '/\s+|[\p{L}\p{N}\p{M}_]+|[^\s\p{L}\p{N}\p{M}_]/u', $text );
			if ( $bytes > self::MAX_HISTORY_BYTES || $tokens > self::MAX_TOKENS ) {
				throw new DomainException( 'synchronous-history-limit-exceeded; resumable-build-required' );
			}
			$history[] = [ 'id' => $cursor->getId(), 'text' => $text ];
			$cursor = $services->getRevisionLookup()->getPreviousRevision( $cursor );
		}
		if ( $cursor ) {
			throw new DomainException( 'synchronous-history-limit-exceeded; resumable-build-required' );
		}
		$history = array_reverse( $history );
		$engine = ( new AttributionEngine() )->analyze( $history );
		return $this->buildAnalysisResponse( $title, $revision, $history, $engine, false, $params['ranges'] );
	}

	private function canBuild( Title $title, int $requestedRevision ): bool {
		try {
			$services = MediaWikiServices::getInstance();
			$revision = $services->getRevisionLookup()->getRevisionByTitle( $title, $requestedRevision );
			if ( !$revision || $revision->getPageId() !== $title->getArticleID() ) { return false; }
			$history = [];
			$rows = [];
			$bytes = 0;
			$tokenCount = 0;
			$cursor = $revision;
			while ( $cursor ) {
				if ( count( $history ) >= 2000 || $cursor->isDeleted( RevisionRecord::DELETED_TEXT ) || $cursor->getMainContentModel() !== CONTENT_MODEL_WIKITEXT ) { return false; }
				$content = $cursor->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
				if ( !method_exists( $content, 'getText' ) ) { return false; }
				$text = $content->getText();
				$bytes += strlen( $text );
				$tokenCount += preg_match_all( '/\s+|[\p{L}\p{N}\p{M}_]+|[^\s\p{L}\p{N}\p{M}_]/u', $text );
				if ( $bytes > 16777216 || $tokenCount > self::MAX_TOKENS ) { return false; }
				$history[] = [ 'id' => $cursor->getId(), 'text' => $text ];
				$rows[] = $this->revisionInfo( $cursor );
				$cursor = $services->getRevisionLookup()->getPreviousRevision( $cursor );
			}
			$history = array_reverse( $history );
			$rows = array_reverse( $rows );
			$provenance = $this->loadProvenance( $title, $revision->getPageId(), $rows, $history );
			return $provenance['history_complete'];
		} catch ( Throwable ) {
			return false;
		}
	}

	private function createBuildJob( Title $title, array $params ): array {
		$services = MediaWikiServices::getInstance();
		$revision = $services->getRevisionLookup()->getRevisionByTitle( $title, $params['revision'] );
		if ( !$revision || $revision->getPageId() !== $title->getArticleID() || $revision->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
			throw new DomainException( 'requested-revision-is-not-readable-on-page' );
		}
		try { $revision->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC ); }
		catch ( Throwable ) { throw new DomainException( 'revision-content-unavailable' ); }
		$db = $services->getConnectionProvider()->getPrimaryDatabase();
		$this->cleanupJobCache( $db );
		$row = $db->selectRow( 'palimpsestblame_job', '*', [
			'pbj_page_id' => $revision->getPageId(),
			'pbj_revision_id' => $revision->getId(),
			'pbj_algorithm' => AttributionEngine::VERSION,
			'pbj_schema_version' => 1,
		], __METHOD__ );
		$queueJob = false;
		if ( $row && $row->pbj_status === 'failed' ) {
			$db->delete( 'palimpsestblame_job_revision', [ 'pbjr_job_id' => (string)$row->pbj_id ], __METHOD__ );
			$db->update( 'palimpsestblame_job', [
				'pbj_status' => 'pending', 'pbj_processed' => 0, 'pbj_total' => null,
				'pbj_state' => json_encode( [ 'cursor_revision_id' => $revision->getId(), 'processed' => 0, 'bytes' => 0, 'tokens' => 0 ], JSON_THROW_ON_ERROR ),
				'pbj_result' => null, 'pbj_error' => null, 'pbj_updated' => wfTimestampNow(),
			], [ 'pbj_id' => (string)$row->pbj_id ], __METHOD__ );
			$row = $db->selectRow( 'palimpsestblame_job', '*', [ 'pbj_id' => (string)$row->pbj_id ], __METHOD__ );
			$queueJob = true;
		}
		if ( !$row ) {
			$active = (int)$db->selectField( 'palimpsestblame_job', 'COUNT(*)', [ 'pbj_status' => [ 'pending', 'running' ] ], __METHOD__ );
			if ( $active >= 3 ) { throw new DomainException( 'job-concurrency-limit-reached' ); }
			$count = (int)$db->selectField( 'palimpsestblame_job', 'COUNT(*)', [], __METHOD__ );
			if ( $count >= 200 ) { $this->evictOldestJobs( $db, $count - 199 ); }
			$remaining = (int)$db->selectField( 'palimpsestblame_job', 'COUNT(*)', [], __METHOD__ );
			if ( $remaining >= 200 ) { throw new DomainException( 'job-cache-cap-reached' ); }
			$id = bin2hex( random_bytes( 16 ) );
			$state = json_encode( [ 'cursor_revision_id' => $revision->getId(), 'processed' => 0, 'bytes' => 0, 'tokens' => 0 ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR );
			$db->insert( 'palimpsestblame_job', [
				'pbj_id' => $id,
				'pbj_page_id' => $revision->getPageId(),
				'pbj_revision_id' => $revision->getId(),
				'pbj_algorithm' => AttributionEngine::VERSION,
				'pbj_schema_version' => 1,
				'pbj_status' => 'pending',
				'pbj_processed' => 0,
				'pbj_total' => null,
				'pbj_state' => $state,
				'pbj_result' => null,
				'pbj_error' => null,
				'pbj_updated' => wfTimestampNow(),
			], __METHOD__ );
			$row = $db->selectRow( 'palimpsestblame_job', '*', [ 'pbj_id' => $id ], __METHOD__ );
			$queueJob = true;
		}
		if ( !$row ) { throw new DomainException( 'job-checkpoint-create-failed' ); }
		if ( $queueJob ) {
			$services->getJobQueueGroup()->push( new BlameBuildJob( [
				'job_id' => (string)$row->pbj_id,
				'namespace' => $title->getNamespace(),
				'title' => $title->getDBkey(),
			] ) );
		}
		return [
			'schema_version' => 1,
			'status' => $row->pbj_status === 'ready' ? 'ready' : ( $row->pbj_status === 'failed' ? 'failed' : 'pending' ),
			'revision_id' => $revision->getId(),
			'job' => [
				'id' => (string)$row->pbj_id,
				'revision_id' => $revision->getId(),
				'status' => (string)$row->pbj_status,
				'processed' => (int)$row->pbj_processed,
				'total' => $row->pbj_total === null ? null : (int)$row->pbj_total,
				'reason' => $row->pbj_error,
				'retryable' => $row->pbj_status === 'pending',
			],
		];
	}

	private function cleanupJobCache( $db ): void {
		$cutoff = wfTimestamp( TS_MW, time() - 2592000 );
		$expired = $db->select( 'palimpsestblame_job', [ 'pbj_id' ], [ 'pbj_updated < ' . $db->addQuotes( $cutoff ) ], __METHOD__, [ 'LIMIT' => 500 ] );
		foreach ( $expired as $row ) {
			$db->delete( 'palimpsestblame_job_revision', [ 'pbjr_job_id' => $row->pbj_id ], __METHOD__ );
			$db->delete( 'palimpsestblame_job', [ 'pbj_id' => $row->pbj_id ], __METHOD__ );
		}
	}

	private function evictOldestJobs( $db, int $count ): void {
		$oldest = $db->select( 'palimpsestblame_job', [ 'pbj_id' ], [ 'pbj_status' => [ 'ready', 'failed' ] ], __METHOD__, [ 'ORDER BY' => 'pbj_updated ASC', 'LIMIT' => max( 1, min( 200, $count ) ) ] );
		foreach ( $oldest as $row ) {
			$db->delete( 'palimpsestblame_job_revision', [ 'pbjr_job_id' => $row->pbj_id ], __METHOD__ );
			$db->delete( 'palimpsestblame_job', [ 'pbj_id' => $row->pbj_id ], __METHOD__ );
		}
	}

	private function readBuildJob( Title $title, array $params ): array {
		if ( $params['jobid'] === '' || $params['revision'] < 1 ) { throw new DomainException( 'job-id-and-pinned-revision-required' ); }
		$services = MediaWikiServices::getInstance();
		$db = $services->getConnectionProvider()->getPrimaryDatabase();
		$row = $db->selectRow( 'palimpsestblame_job', '*', [ 'pbj_id' => $params['jobid'] ], __METHOD__ );
		if ( !$row || (int)$row->pbj_page_id !== $title->getArticleID() || (int)$row->pbj_revision_id !== $params['revision'] ||
			$row->pbj_algorithm !== AttributionEngine::VERSION || (int)$row->pbj_schema_version !== 1 ) {
			throw new DomainException( 'job-does-not-match-page-and-pinned-revision' );
		}
		$target = $services->getRevisionLookup()->getRevisionByTitle( $title, $params['revision'] );
		if ( !$target || $target->getPageId() !== (int)$row->pbj_page_id || $target->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
			throw new DomainException( 'job-target-revision-unavailable' );
		}
		$state = json_decode( $row->pbj_state, true, 64, JSON_THROW_ON_ERROR );
		$history = [];
		$result = $row->pbj_status === 'ready' && $row->pbj_result ? json_decode( $row->pbj_result, true, 128, JSON_THROW_ON_ERROR ) : null;
		$checkpointRows = $db->select(
			'palimpsestblame_job_revision',
			[ 'pbjr_revision_id', 'pbjr_sha256', 'pbjr_text' ],
			[ 'pbjr_job_id' => (string)$row->pbj_id ],
			__METHOD__,
			[ 'ORDER BY' => 'pbjr_order DESC' ]
		);
		foreach ( $checkpointRows as $checkpoint ) {
			$item = [ 'id' => (int)$checkpoint->pbjr_revision_id, 'text' => $checkpoint->pbjr_text ];
			$history[] = $item;
			$record = $services->getRevisionLookup()->getRevisionById( (int)$item['id'] );
			if ( !$record || $record->getPageId() !== (int)$row->pbj_page_id || $record->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
				throw new DomainException( 'cached-history-now-unavailable' );
			}
			try { $record->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC ); }
			catch ( Throwable ) { throw new DomainException( 'cached-history-now-unavailable' ); }
			if ( !hash_equals( (string)$checkpoint->pbjr_sha256, hash( 'sha256', $item['text'] ) ) ) {
				throw new DomainException( 'cached-history-checkpoint-integrity-failed' );
			}
		}
		if ( $row->pbj_status === 'ready' && ( !$result || count( $history ) !== (int)$row->pbj_processed || !$history || end( $history )['id'] !== $target->getId() ||
			!isset( $result['tokens'], $result['events'], $result['algorithm'] ) || !is_array( $result['tokens'] ) || !is_array( $result['events'] ) || !is_array( $result['algorithm'] ) ) ) {
			throw new DomainException( 'cached-build-result-integrity-failed' );
		}
		$job = [
			'id' => (string)$row->pbj_id,
			'status' => (string)$row->pbj_status,
			'processed' => (int)$row->pbj_processed,
			'total' => $row->pbj_total === null ? null : (int)$row->pbj_total,
			'reason' => $row->pbj_error,
			'retryable' => $row->pbj_status === 'pending',
			'revision_id' => $target->getId(),
		];
		if ( $row->pbj_status === 'ready' && isset( $result ) ) {
			$engine = [ 'tokens' => $result['tokens'], 'events' => $result['events'], 'algorithm' => $result['algorithm'] ];
			return $this->buildAnalysisResponse( $title, $target, $history, $engine, false, $params['ranges'] ) + [ 'job' => $job ];
		}
		return [ 'schema_version' => 1, 'status' => (string)$row->pbj_status, 'revision_id' => $params['revision'], 'job' => $job ];
	}

	private function buildAnalysisResponse( Title $title, RevisionRecord $revision, array $history, array $engine, bool $truncated, string $ranges = '' ): array {
		$services = MediaWikiServices::getInstance();
		$revisionRows = [];
		foreach ( $history as $item ) {
			$record = $services->getRevisionLookup()->getRevisionById( $item['id'] );
			if ( !$record || $record->getPageId() !== $revision->getPageId() ) {
				throw new DomainException( 'revision-chain-invalid' );
			}
			$revisionRows[] = $this->revisionInfo( $record );
		}
		$currentText = end( $history )['text'];
		$latestLocalRevision = $services->getRevisionLookup()->getRevisionByTitle( $title );
		$map = $this->loadProvenance( $title, $revision->getPageId(), $revisionRows, $history );
		$snapshot = $this->snapshotInfo( $revision );
		foreach ( $revisionRows as $row ) {
			if ( $row['revision_id'] === $revision->getId() ) { $snapshot = $row; break; }
		}
		$render = $this->renderMappedHtml( $title, $revision, $engine['tokens'], $currentText );
		$coverage = [
			'history_complete' => !$truncated && $map['history_complete'],
			'provenance_status' => $map['status'],
			'source_wiki' => $map['source_wiki'],
			'source_page_id' => $map['source_page_id'],
			'source_anchor_revision_id' => $map['source_anchor_revision_id'],
			'source_anchor_timestamp' => $map['source_anchor_timestamp'],
			'earliest_timestamp' => $revisionRows[0]['timestamp'] ?? null,
			'latest_timestamp' => $latestLocalRevision ? self::timestampIso( $latestLocalRevision->getTimestamp() ) : null,
			'reasons' => array_values( array_filter( [
				$truncated ? 'revision-window-truncated' : null,
				...$map['reasons'],
				...$render['reasons'],
			] ) ),
		];
		$spanRows = array_map( static function ( array $token ): array {
			$row = $token;
			unset( $row['start'], $row['end'], $row['utf16_start'], $row['utf16_end'] );
			$row['start'] = $token['utf16_start'];
			$row['end'] = $token['utf16_end'];
			$row['confidence'] = $token['ambiguous'] ? 'ambiguous' : 'aligned';
			return $row;
		}, $engine['tokens'] );
		$result = [
			'schema_version' => 1,
			'status' => 'ready',
			'page' => [ 'id' => $revision->getPageId(), 'title' => $title->getPrefixedText(), 'language' => $services->getMainConfig()->get( 'LanguageCode' ), 'latest_revision_id' => $services->getRevisionLookup()->getRevisionByTitle( $title )?->getId() ],
			'snapshot' => $snapshot,
			'coverage' => $coverage,
			'source_text' => $currentText,
			'html' => $render['html'],
			'spans' => $spanRows,
			'revisions' => $revisionRows,
			'events' => $engine['events'],
			'algorithm' => $engine['algorithm'],
			'mapping' => [ 'mapped_characters' => $render['mapped_characters'], 'unmapped_reasons' => $render['reasons'] ],
		];
		if ( $ranges !== '' ) {
			$result['selection'] = $this->selection( $ranges, $currentText, $engine['tokens'], $engine['events'] );
		}
		return $result;
	}

	private function versions( Title $title, array $params ): array {
		$services = MediaWikiServices::getInstance();
		$mode = $params['mode'];
		if ( $mode === 'range' ) {
			$from = $this->parseUtcBound( $params['from'], false );
			$to = $this->parseUtcBound( $params['to'], true );
			if ( $from === null || $to === null || $from > $to ) { throw new DomainException( 'invalid-or-reversed-range' ); }
			$singleBound = null;
		} else {
			if ( $params['from'] !== '' && $params['to'] !== '' && $params['from'] !== $params['to'] ) {
				throw new DomainException( 'conflicting-single-date-bounds' );
			}
			$singleValue = $params['to'] !== '' ? $params['to'] : $params['from'];
			$singleBound = $this->parseUtcBound( $singleValue, $mode === 'asof' );
			if ( $singleBound === null ) { throw new DomainException( 'invalid-date-bound' ); }
			$from = null;
			$to = null;
		}
		$cursor = $services->getRevisionLookup()->getRevisionByTitle( $title );
		if ( !$cursor ) {
			throw new DomainException( 'page-has-no-readable-revisions' );
		}
		$matches = [];
		$scanned = 0;
		$lastScannedId = null;
		$cursorFound = $params['cursor'] === '';
		$cursorId = $params['cursor'] === '' ? null : $this->decodeVersionCursor( $params['cursor'], $title, $mode, $params['from'], $params['to'] );
		while ( $cursor && $scanned++ < 5000 ) {
			if ( !$cursorFound ) {
				if ( $cursor->getId() === $cursorId ) { $cursorFound = true; }
				$cursor = $services->getRevisionLookup()->getPreviousRevision( $cursor );
				continue;
			}
			$lastScannedId = $cursor->getId();
			$timestamp = $cursor->getTimestamp();
			$ts = DateTimeImmutable::createFromFormat( 'YmdHis', $timestamp, new DateTimeZone( 'UTC' ) );
			$time = $ts ? $ts->getTimestamp() : 0;
			$hit = match ( $mode ) {
				'asof' => $time <= $singleBound,
				'before' => $time < $singleBound,
				'range' => $time >= $from && $time <= $to,
			};
			if ( $mode !== 'range' && $hit ) {
				$matches[] = $this->revisionInfo( $cursor );
				break;
			}
			if ( $mode === 'range' && $hit ) {
				$matches[] = $this->revisionInfo( $cursor );
			}
			$cursor = $services->getRevisionLookup()->getPreviousRevision( $cursor );
		}
		if ( $params['cursor'] !== '' && !$cursorFound ) {
			throw new DomainException( 'invalid-or-expired-continuation' );
		}
		if ( $cursor && $scanned >= 5000 && !$matches ) {
			throw new DomainException( 'date-scan-limit-exceeded' );
		}
		usort( $matches, static fn ( $a, $b ) => strcmp( $b['timestamp'], $a['timestamp'] ) ?: ( $b['revision_id'] <=> $a['revision_id'] ) );
		$hasMore = count( $matches ) > $params['limit'];
		$page = array_slice( $matches, 0, $params['limit'] );
		$continuation = null;
		if ( $mode === 'range' && $hasMore && $page ) {
			$last = end( $page );
			$continuation = $this->encodeVersionCursor( $last['revision_id'], $title, $mode, $params['from'], $params['to'] );
		} elseif ( $mode === 'range' && $cursor !== null && $scanned >= 5000 && $lastScannedId !== null ) {
			$continuation = $this->encodeVersionCursor( $lastScannedId, $title, $mode, $params['from'], $params['to'] );
		}
		$provenance = $this->provenanceAnchor( $title );
		return [
			'schema_version' => 1,
			'status' => 'ready',
			'mode' => $mode,
			'bounds' => [
				'from' => $from === null ? null : gmdate( 'Y-m-d\TH:i:s\Z', $from ),
				'to' => gmdate( 'Y-m-d\TH:i:s\Z', $mode === 'range' ? $to : $singleBound ),
				'timezone' => 'UTC',
				'same_second_order' => 'revision_id_descending',
			],
			'versions' => $mode === 'range' ? $page : array_slice( $matches, 0, 1 ),
			'selected_revision_id' => $mode === 'range' ? null : ( $matches[0]['revision_id'] ?? null ),
			'continuation' => $continuation,
			'coverage' => [
				'history_complete' => $cursor === null,
				'source_anchor_timestamp' => $provenance['timestamp'],
				'provenance_status' => $provenance['status'],
				'reasons' => array_values( array_filter( [ $cursor === null ? null : 'version-window-limited', $provenance['reason'] ] ) ),
			],
		];
	}

	private function provenanceAnchor( Title $title ): array {
		$services = MediaWikiServices::getInstance();
		$directory = $services->getConfigFactory()->makeConfig( 'main' )->get( 'PalimpsestBlameProvenanceDirectory' );
		$language = (string)$services->getMainConfig()->get( 'LanguageCode' );
		if ( !is_string( $directory ) || $directory === '' ) { return [ 'timestamp' => null, 'status' => 'not-configured', 'reason' => null ]; }
		$path = rtrim( $directory, DIRECTORY_SEPARATOR ) . DIRECTORY_SEPARATOR . $language . '.json';
		if ( !is_file( $path ) || filesize( $path ) > 16777216 ) { return [ 'timestamp' => null, 'status' => 'invalid', 'reason' => 'provenance-bundle-missing-or-too-large' ]; }
		try { $bundle = json_decode( file_get_contents( $path ), true, 128, JSON_THROW_ON_ERROR ); }
		catch ( Throwable ) { return [ 'timestamp' => null, 'status' => 'invalid', 'reason' => 'provenance-bundle-invalid-json' ]; }
		if ( !is_array( $bundle ) || ( $bundle['schema_version'] ?? null ) !== 1 || ( $bundle['language'] ?? null ) !== $language || !isset( $bundle['payload'], $bundle['sha256'] ) ) {
			return [ 'timestamp' => null, 'status' => 'invalid', 'reason' => 'provenance-bundle-invalid-header' ];
		}
		try { $canonical = json_encode( $this->canonicalize( $bundle['payload'] ), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR ); }
		catch ( Throwable ) { return [ 'timestamp' => null, 'status' => 'invalid', 'reason' => 'provenance-bundle-invalid-payload' ]; }
		if ( !hash_equals( (string)$bundle['sha256'], hash( 'sha256', $canonical ) ) ) { return [ 'timestamp' => null, 'status' => 'invalid', 'reason' => 'provenance-bundle-checksum-mismatch' ]; }
		foreach ( $bundle['payload']['pages'] ?? [] as $page ) {
			if ( (int)( $page['local_page_id'] ?? 0 ) === $title->getArticleID() && ( $page['title'] ?? null ) === $title->getPrefixedText() ) {
				return [ 'timestamp' => $page['source_anchor_timestamp'] ?? null, 'status' => 'verified', 'reason' => null ];
			}
		}
		return [ 'timestamp' => null, 'status' => 'not-imported', 'reason' => null ];
	}

	private function parseUtcBound( string $value, bool $endOfDay ): ?int {
		if ( preg_match( '/^\d{4}-\d{2}-\d{2}$/', $value ) ) {
			[ $year, $month, $day ] = array_map( 'intval', explode( '-', $value ) );
			if ( !checkdate( $month, $day, $year ) ) { return null; }
			$dt = DateTimeImmutable::createFromFormat( '!Y-m-d', $value, new DateTimeZone( 'UTC' ) );
			if ( !$dt || $dt->format( 'Y-m-d' ) !== $value ) { return null; }
			return $endOfDay ? $dt->getTimestamp() + 86399 : $dt->getTimestamp();
		}
		if ( !preg_match( '/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/', $value, $parts ) ) {
			return null;
		}
		if ( !checkdate( (int)$parts[2], (int)$parts[3], (int)$parts[1] ) || (int)$parts[4] > 23 || (int)$parts[5] > 59 || (int)$parts[6] > 59 ) { return null; }
		try {
			return ( new DateTimeImmutable( $value ) )->setTimezone( new DateTimeZone( 'UTC' ) )->getTimestamp();
		} catch ( Throwable ) {
			return null;
		}
	}

	private function encodeVersionCursor( int $lastId, Title $title, string $mode, string $from, string $to ): string {
		$json = json_encode( [ 'v' => 1, 'id' => $lastId, 'title' => $title->getPrefixedDBkey(), 'mode' => $mode, 'from' => $from, 'to' => $to ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR );
		return rtrim( strtr( base64_encode( $json ), '+/', '-_' ), '=' );
	}

	private function decodeVersionCursor( string $cursor, Title $title, string $mode, string $from, string $to ): int {
		$decoded = base64_decode( strtr( $cursor, '-_', '+/' ), true );
		try { $data = $decoded === false ? null : json_decode( $decoded, true, 8, JSON_THROW_ON_ERROR ); }
		catch ( Throwable ) { $data = null; }
		if ( !is_array( $data ) || ( $data['v'] ?? null ) !== 1 || !is_int( $data['id'] ?? null ) || ( $data['title'] ?? null ) !== $title->getPrefixedDBkey() || ( $data['mode'] ?? null ) !== $mode || ( $data['from'] ?? null ) !== $from || ( $data['to'] ?? null ) !== $to ) {
			throw new DomainException( 'invalid-or-expired-continuation' );
		}
		return $data['id'];
	}

	private function revisionInfo( RevisionRecord $revision ): array {
		$user = $revision->getUser( RevisionRecord::FOR_PUBLIC );
		$comment = $revision->getComment( RevisionRecord::FOR_PUBLIC );
		$userName = $user ? $user->getName() : null;
		$title = Title::newFromID( $revision->getPageId() );
		$url = $title ? $title->getLocalURL( [ 'oldid' => $revision->getId() ] ) : '';
		$parent = $revision->getParentId();
		$diff = $title ? $title->getLocalURL( [ 'diff' => $revision->getId(), 'oldid' => $parent ?: 'prev' ] ) : '';
		$contrib = $userName ? \MediaWiki\SpecialPage\SpecialPage::getTitleFor( 'Contributions', $userName )->getLocalURL() : null;
		return [
			'revision_id' => $revision->getId(),
			'parent_id' => $parent,
			'timestamp' => self::timestampIso( $revision->getTimestamp() ),
			'user' => $userName,
			'comment' => $comment ? $comment->text : null,
			'minor' => $revision->isMinor(),
			'content_model' => $revision->getMainContentModel(),
			'source' => null,
			'url' => $url,
			'diff_url' => $diff,
			'contributions_url' => $contrib,
		];
	}

	private static function timestampIso( string $timestamp ): string {
		$parsed = DateTimeImmutable::createFromFormat( '!YmdHis', $timestamp, new DateTimeZone( 'UTC' ) );
		if ( !$parsed || $parsed->format( 'YmdHis' ) !== $timestamp ) { return $timestamp; }
		return $parsed->format( 'Y-m-d\TH:i:s\Z' );
	}

	private function snapshotInfo( RevisionRecord $revision ): array {
		return $this->revisionInfo( $revision );
	}

	private function loadProvenance( Title $title, int $pageId, array &$revisionRows, array $history ): array {
		$services = MediaWikiServices::getInstance();
		$config = $services->getConfigFactory()->makeConfig( 'main' );
		$directory = $config->get( 'PalimpsestBlameProvenanceDirectory' );
		$language = (string)$services->getMainConfig()->get( 'LanguageCode' );
		$empty = [ 'status' => 'not-imported', 'history_complete' => true, 'source_wiki' => null, 'source_page_id' => null, 'source_anchor_revision_id' => null, 'source_anchor_timestamp' => null, 'reasons' => [] ];
		$containsImportedIdentity = (bool)array_filter( $revisionRows, static fn ( $row ) => str_starts_with( (string)( $row['user'] ?? '' ), 'Imported>' ) );
		if ( !is_string( $directory ) || $directory === '' ) {
			if ( $containsImportedIdentity ) { throw new DomainException( 'imported-revision-provenance-unavailable' ); }
			return $empty;
		}
		$path = rtrim( $directory, DIRECTORY_SEPARATOR ) . DIRECTORY_SEPARATOR . $language . '.json';
		if ( !is_file( $path ) || filesize( $path ) > 16777216 ) {
			if ( $containsImportedIdentity ) { throw new DomainException( 'provenance-bundle-missing-or-too-large' ); }
			return $empty;
		}
		try {
			$bundle = json_decode( file_get_contents( $path ), true, 128, JSON_THROW_ON_ERROR );
		} catch ( Throwable ) {
			if ( $containsImportedIdentity ) { throw new DomainException( 'provenance-bundle-invalid-json' ); }
			return $empty;
		}
		if ( !is_array( $bundle ) || ( $bundle['schema_version'] ?? null ) !== 1 || ( $bundle['language'] ?? null ) !== $language || !isset( $bundle['payload'], $bundle['sha256'] ) ) {
			if ( $containsImportedIdentity ) { throw new DomainException( 'provenance-bundle-invalid-header' ); }
			return $empty;
		}
		$canonical = json_encode( $this->canonicalize( $bundle['payload'] ), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR );
		if ( !hash_equals( (string)$bundle['sha256'], hash( 'sha256', $canonical ) ) ) {
			if ( $containsImportedIdentity ) { throw new DomainException( 'provenance-bundle-checksum-mismatch' ); }
			return $empty;
		}
		foreach ( $bundle['payload']['pages'] ?? [] as $page ) {
			if ( (int)( $page['local_page_id'] ?? 0 ) !== $pageId ) { continue; }
			if ( ( $page['title'] ?? null ) !== $title->getPrefixedText() ) {
				throw new DomainException( 'provenance-page-title-mismatch' );
			}
			$records = [];
			foreach ( $page['revisions'] ?? [] as $record ) { $records[(int)$record['local_revision_id']] = $record; }
			$anchorTimestamp = (string)( $page['source_anchor_timestamp'] ?? '' );
			$hashes = [];
			foreach ( $history as $item ) { $hashes[$item['id']] = hash( 'sha256', $item['text'] ); }
			foreach ( $revisionRows as &$row ) {
				$record = $records[$row['revision_id']] ?? null;
				if ( !$record ) {
					if ( str_starts_with( (string)( $row['user'] ?? '' ), 'Imported>' ) || ( $anchorTimestamp !== '' && $row['timestamp'] <= $anchorTimestamp ) ) {
						unset( $row );
						throw new DomainException( 'imported-revision-provenance-record-missing' );
					}
					continue;
				}
				$actual = $hashes[$row['revision_id']] ?? null;
				if ( !$actual || !hash_equals( (string)( $record['sha256'] ?? '' ), $actual ) || ( $record['timestamp'] ?? null ) !== $row['timestamp'] || (int)( $record['local_parent_id'] ?? -1 ) !== (int)$row['parent_id'] || ( $record['user'] ?? null ) !== $row['user'] || ( $record['comment'] ?? null ) !== $row['comment'] || (bool)( $record['minor'] ?? false ) !== (bool)$row['minor'] || ( $record['content_model'] ?? null ) !== $row['content_model'] ) {
					unset( $row );
					throw new DomainException( 'provenance-record-does-not-match-local-revision' );
				}
				$sourceUrl = $record['source_url'] ?? null;
				$urlParts = is_string( $sourceUrl ) ? parse_url( $sourceUrl ) : false;
				$wikiHost = preg_replace( '/wiki$/', '.wikipedia.org', (string)$bundle['source_wiki'] );
				if ( !$urlParts || ( $urlParts['scheme'] ?? '' ) !== 'https' || strtolower( $urlParts['host'] ?? '' ) !== strtolower( $wikiHost ) ) {
					unset( $row );
					throw new DomainException( 'provenance-source-url-invalid' );
				}
				$row['source'] = [
					'wiki' => $bundle['source_wiki'],
					'page_id' => $page['source_page_id'],
					'revision_id' => $record['source_revision_id'],
					'parent_id' => $record['source_parent_id'],
					'url' => $sourceUrl,
					'user' => $row['user'] === null ? null : ( $record['source_user'] ?? null ),
					'comment' => $row['comment'] === null ? null : ( $record['comment'] ?? null ),
				];
			}
			unset( $row );
			return [
				'status' => 'verified',
				'history_complete' => (bool)( $page['history_complete'] ?? false ),
				'source_wiki' => $bundle['source_wiki'] ?? null,
				'source_page_id' => $page['source_page_id'] ?? null,
				'source_anchor_revision_id' => $page['source_anchor_revision_id'] ?? null,
				'source_anchor_timestamp' => $page['source_anchor_timestamp'] ?? null,
				'reasons' => [],
			];
		}
		if ( $containsImportedIdentity ) {
			throw new DomainException( 'provenance-page-record-missing' );
		}
		return $empty;
	}

	private function canonicalize( mixed $value ): mixed {
		if ( !is_array( $value ) ) { return $value; }
		if ( array_is_list( $value ) ) { return array_map( $this->canonicalize( ... ), $value ); }
		ksort( $value, SORT_STRING );
		foreach ( $value as &$child ) { $child = $this->canonicalize( $child ); }
		return $value;
	}

	private function renderMappedHtml( Title $title, RevisionRecord $revision, array $tokens, string $source ): array {
		$services = MediaWikiServices::getInstance();
		$page = $services->getPageStore()->getPageById( $revision->getPageId() );
		if ( !$page ) { return [ 'html' => '', 'mapped_characters' => 0, 'reasons' => [ 'page-render-unavailable' ] ]; }
		$options = ParserOptions::newFromUser( $this->getUser() );
		$options->setUseParsoid( true );
		$status = $services->getParserOutputAccess()->getParserOutput(
			$page,
			$options,
			$revision
		);
		if ( !$status->isOK() || !$status->getValue() instanceof ParserOutput ) {
			return [ 'html' => '', 'mapped_characters' => 0, 'reasons' => [ 'parsoid-render-unavailable' ] ];
		}
		$output = $status->getValue();
		$holder = $output->getContentHolder();
		if ( !$holder->isParsoidContent() ) {
			return [ 'html' => $holder->getAsHtmlString() ?? '', 'mapped_characters' => 0, 'reasons' => [ 'parsoid-pagebundle-unavailable' ] ];
		}
		$bundle = $holder->getBasePageBundle();
		if ( ( $bundle->parsoid['offsetType'] ?? 'byte' ) !== 'byte' ) {
			return [ 'html' => $holder->getAsHtmlString() ?? '', 'mapped_characters' => 0, 'reasons' => [ 'unsupported-parsoid-offset-type' ] ];
		}
		$ids = $bundle->parsoid['ids'] ?? [];
		$html = $holder->getAsHtmlString() ?? '';
		$mapped = ( new \MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidTextMapper() )->map( $html, $source, $ids, $tokens );
		$normalizedHtml = ( new \MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidLinkNormalizer() )->normalize(
			$mapped['html'],
			static function ( string $targetText ): ?string {
				$target = Title::newFromText( $targetText );
				return $target ? $target->getLocalURL() : null;
			}
		);
		return [ 'html' => $normalizedHtml, 'mapped_characters' => $mapped['mapped_characters'], 'reasons' => $mapped['unmapped_reasons'] ];
	}

	private function selection( string $encoded, string $source, array $tokens, array $events ): array {
		try { $ranges = json_decode( $encoded, true, 16, JSON_THROW_ON_ERROR ); }
		catch ( JsonException ) { throw new DomainException( 'selection-ranges-invalid-json' ); }
		if ( !is_array( $ranges ) || count( $ranges ) > 64 ) { throw new DomainException( 'selection-range-limit-exceeded' ); }
		$revisionIds = [];
		$tokenIds = [];
		$ambiguous = false;
		foreach ( $ranges as $range ) {
			if ( !isset( $range['start'], $range['end'] ) || !is_int( $range['start'] ) || !is_int( $range['end'] ) || $range['start'] < 0 || $range['end'] <= $range['start'] || $range['end'] > SourceTokenizer::utf16Length( $source ) ) {
				throw new DomainException( 'selection-range-out-of-bounds' );
			}
			foreach ( $tokens as $token ) {
				if ( $token['utf16_start'] < $range['end'] && $token['utf16_end'] > $range['start'] ) {
					$revisionIds[$token['revision_id']] = true;
					$tokenIds[$token['token_id']] = true;
					foreach ( $token['lineage_ids'] as $ancestor ) { $tokenIds[$ancestor] = true; }
					$ambiguous = $ambiguous || $token['ambiguous'];
				}
			}
		}
		$selectedEvents = array_values( array_filter( $events, static fn ( $event ) =>
			array_intersect( $event['token_ids'], array_keys( $tokenIds ) ) ||
			isset( $tokenIds[$event['left_token_id'] ?? ''] ) || isset( $tokenIds[$event['right_token_id'] ?? ''] )
		) );
		return [
			'ranges' => $ranges,
			'revision_ids' => array_map( 'intval', array_keys( $revisionIds ) ),
			'events' => $selectedEvents,
			'ambiguous' => $ambiguous || (bool)array_filter( $selectedEvents, static fn ( $event ) => $event['ambiguous'] ),
			'reasons' => [],
		];
	}

	public function getDescription() {
		return 'Analyze text attribution and historical revisions for a page.';
	}
}

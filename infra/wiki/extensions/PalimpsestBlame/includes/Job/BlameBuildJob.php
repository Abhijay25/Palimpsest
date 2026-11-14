<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Job;

use DomainException;
use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionEngine;
use MediaWiki\JobQueue\Job;
use MediaWiki\Logger\LoggerFactory;
use MediaWiki\MediaWikiServices;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;
use MediaWiki\Title\Title;
use Throwable;

final class BlameBuildJob extends Job {
	private const MAX_REVISIONS = 2000;
	private const MAX_HISTORY_BYTES = 16777216;
	private const MAX_TOKENS = AttributionEngine::MAX_HISTORY_TOKENS;
	private const STALE_CLAIM_SECONDS = 600;
	protected $removeDuplicates = true;

	public function __construct( Title $title, array $params ) {
		parent::__construct( 'palimpsestblamebuild', $title, $params );
	}

	public function run() {
		$services = MediaWikiServices::getInstance();
		$db = $services->getConnectionProvider()->getPrimaryDatabase();
		$id = (string)( $this->params['job_id'] ?? '' );
		$row = $db->selectRow( 'palimpsestblame_job', '*', [ 'pbj_id' => $id ], __METHOD__ );
		if ( !$row || !in_array( $row->pbj_status, [ 'pending', 'running' ], true ) ||
			$row->pbj_algorithm !== AttributionEngine::VERSION || (int)$row->pbj_schema_version !== 1 ) {
			return true;
		}
		$now = wfTimestampNow();
		$leaseTimestamp = $now;
		$claimConditions = [ 'pbj_id' => $id, 'pbj_status' => $row->pbj_status ];
		if ( $row->pbj_status === 'running' ) {
			if ( (int)wfTimestamp( TS_UNIX, $row->pbj_updated ) > time() - self::STALE_CLAIM_SECONDS ) { return true; }
			$claimConditions['pbj_updated'] = $row->pbj_updated;
		}
		$db->update( 'palimpsestblame_job', [ 'pbj_status' => 'running', 'pbj_updated' => $now ], $claimConditions, __METHOD__ );
		if ( $db->affectedRows() !== 1 ) { return true; }
		try {
			$state = json_decode( $row->pbj_state, true, 64, JSON_THROW_ON_ERROR );
			$history = [];
			$cursorId = (int)( $state['cursor_revision_id'] ?? 0 );
			$bytes = (int)( $state['bytes'] ?? 0 );
			$tokens = (int)( $state['tokens'] ?? 0 );
			$batchSize = (int)$services->getMainConfig()->get( 'PalimpsestBlameJobBatchRevisions' );
			$batchSize = min( 10, max( 1, $batchSize ) );
			$processedThisBatch = 0;
			$complete = $cursorId === 0;
			while ( !$complete && $processedThisBatch < $batchSize ) {
				if ( (int)$row->pbj_processed + $processedThisBatch >= self::MAX_REVISIONS ) { throw new DomainException( 'history-revision-limit-exceeded' ); }
				$revision = $services->getRevisionLookup()->getRevisionById( $cursorId );
				if ( !$revision || $revision->getPageId() !== (int)$row->pbj_page_id ) { throw new DomainException( 'revision-chain-invalid' ); }
				if ( $revision->isDeleted( RevisionRecord::DELETED_TEXT ) ) { throw new DomainException( 'history-contains-hidden-content' ); }
				$content = $revision->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
				if ( !method_exists( $content, 'getText' ) || $revision->getMainContentModel() !== CONTENT_MODEL_WIKITEXT ) { throw new DomainException( 'unsupported-content-model' ); }
				$text = $content->getText();
				$bytes += strlen( $text );
				if ( $bytes > self::MAX_HISTORY_BYTES ) { throw new DomainException( 'history-byte-limit-exceeded' ); }
				$revisionTokens = preg_match_all( '/\s+|[\p{L}\p{N}\p{M}_]+|[^\s\p{L}\p{N}\p{M}_]/u', $text );
				if ( $revisionTokens === false ) { throw new DomainException( 'history-text-invalid' ); }
				if ( $revisionTokens > AttributionEngine::MAX_TOKENS_PER_REVISION ) { throw new DomainException( 'revision-token-limit-exceeded' ); }
				$tokens += $revisionTokens;
				if ( $tokens > self::MAX_TOKENS ) { throw new DomainException( 'history-token-limit-exceeded' ); }
				$db->insert( 'palimpsestblame_job_revision', [
					'pbjr_job_id' => $id,
					'pbjr_page_id' => $revision->getPageId(),
					'pbjr_revision_id' => $revision->getId(),
					'pbjr_order' => (int)$row->pbj_processed + $processedThisBatch,
					'pbjr_sha256' => hash( 'sha256', $text ),
					'pbjr_text' => $text,
				], __METHOD__, [ 'IGNORE' ] );
				$cursorId = (int)$revision->getParentId();
				$complete = $cursorId === 0;
				$processedThisBatch++;
			}

			$processed = (int)$row->pbj_processed + $processedThisBatch;
			if ( $complete ) {
				$res = $db->select( 'palimpsestblame_job_revision', [ 'pbjr_revision_id', 'pbjr_text' ], [ 'pbjr_job_id' => $id ], __METHOD__, [ 'ORDER BY' => 'pbjr_order DESC' ] );
				$historyOldestFirst = [];
				foreach ( $res as $record ) { $historyOldestFirst[] = [ 'id' => (int)$record->pbjr_revision_id, 'text' => $record->pbjr_text ]; }
				$analysis = ( new AttributionEngine() )->analyze( $historyOldestFirst );
				$result = [ 'tokens' => $analysis['tokens'], 'events' => $analysis['events'], 'algorithm' => $analysis['algorithm'] ];
				$db->update( 'palimpsestblame_job', [
					'pbj_status' => 'ready',
					'pbj_processed' => $processed,
					'pbj_total' => $processed,
					'pbj_state' => json_encode( [ 'cursor_revision_id' => 0, 'processed' => $processed, 'bytes' => $bytes, 'tokens' => $tokens ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR ),
					'pbj_result' => json_encode( $result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR ),
					'pbj_error' => null,
					'pbj_updated' => wfTimestampNow(),
				], [ 'pbj_id' => $id, 'pbj_status' => 'running', 'pbj_updated' => $leaseTimestamp ], __METHOD__ );
				if ( $db->affectedRows() !== 1 ) { return true; }
			} else {
				$db->update( 'palimpsestblame_job', [
					'pbj_status' => 'pending',
					'pbj_processed' => $processed,
					'pbj_state' => json_encode( [ 'cursor_revision_id' => $cursorId, 'processed' => $processed, 'bytes' => $bytes, 'tokens' => $tokens ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR ),
					'pbj_updated' => wfTimestampNow(),
				], [ 'pbj_id' => $id, 'pbj_status' => 'running', 'pbj_updated' => $leaseTimestamp ], __METHOD__ );
				if ( $db->affectedRows() !== 1 ) { return true; }
				$services->getJobQueueGroup()->push( new self( $this->getTitle(), [ 'job_id' => $id ] ) );
			}
			return true;
		} catch ( DomainException $e ) {
			$db->update( 'palimpsestblame_job', [ 'pbj_status' => 'failed', 'pbj_error' => $e->getMessage(), 'pbj_updated' => wfTimestampNow() ], [ 'pbj_id' => $id, 'pbj_status' => 'running', 'pbj_updated' => $leaseTimestamp ], __METHOD__ );
			return true;
		} catch ( Throwable $e ) {
			$db->update( 'palimpsestblame_job', [ 'pbj_status' => 'failed', 'pbj_error' => 'job-processing-failed', 'pbj_updated' => wfTimestampNow() ], [ 'pbj_id' => $id, 'pbj_status' => 'running', 'pbj_updated' => $leaseTimestamp ], __METHOD__ );
			LoggerFactory::getInstance( 'PalimpsestBlame' )->error( 'Build job failed', [ 'exception' => $e ] );
			return true;
		}
	}
}

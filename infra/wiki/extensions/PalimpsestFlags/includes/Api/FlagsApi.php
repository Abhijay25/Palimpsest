<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestFlags\Api;

use JsonException;
use MediaWiki\Api\ApiBase;
use MediaWiki\Api\ApiMain;
use MediaWiki\MediaWikiServices;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;
use Throwable;
use Wikimedia\ParamValidator\ParamValidator;
use Wikimedia\ParamValidator\TypeDef\NumericDef;

/** Server-side bridge: audit content never traverses the browser. */
final class FlagsApi extends ApiBase {
	private const CACHE_TTL = 86400;
	private const ERROR_CACHE_TTL = 60;

	public function __construct( ApiMain $main, string $moduleName, string $modulePrefix = '' ) {
		parent::__construct( $main, $moduleName, $modulePrefix );
	}

	public function execute() {
		$params = $this->extractRequestParams();
		$services = MediaWikiServices::getInstance();
		$config = $services->getMainConfig();
		if ( trim( (string)$config->get( 'PalimpsestFlagsApiUrl' ) ) === '' ) {
			$this->respond( [ 'status' => 'disabled', 'flags' => [], 'partial' => false, 'error' => null ] );
			return;
		}
		$oldId = (int)$params['oldid'];
		$newId = (int)$params['diff'];
		if ( $oldId <= 0 || $newId <= 0 || $oldId === $newId ) {
			$this->respond( $this->error( 'invalid-revision-pair' ) );
			return;
		}
		$lookup = $services->getRevisionLookup();
		$old = $lookup->getRevisionById( $oldId );
		$new = $lookup->getRevisionById( $newId );
		if ( !$old || !$new || $old->getPageId() !== $new->getPageId() ||
			$old->isDeleted( RevisionRecord::DELETED_TEXT ) || $new->isDeleted( RevisionRecord::DELETED_TEXT ) ) {
			$this->respond( $this->error( 'revision-unavailable' ) );
			return;
		}
		$title = \MediaWiki\Title\Title::newFromLinkTarget( $new->getPageAsLinkTarget() );
		if ( !$services->getPermissionManager()->userCan( 'read', $this->getUser(), $title ) ) {
			$this->respond( $this->error( 'permissiondenied' ) );
			return;
		}
		$version = (string)$config->get( 'PalimpsestFlagsApiVersion' );
		$cache = $services->getMainWANObjectCache();
		$key = $cache->makeKey( 'palimpsestflags', 'audit', $oldId, $newId, $version );
		$cached = $cache->get( $key );
		if ( is_array( $cached ) ) {
			$this->respond( $cached );
			return;
		}
		try {
			$oldContent = $old->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
			$newContent = $new->getContentOrThrow( SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC );
			if ( !method_exists( $oldContent, 'getText' ) || !method_exists( $newContent, 'getText' ) ||
				$old->getMainContentModel() !== CONTENT_MODEL_WIKITEXT || $new->getMainContentModel() !== CONTENT_MODEL_WIKITEXT ) {
				$result = $this->error( 'unsupported-content-model' );
			} else {
				$payload = [
					'lang_code' => $title->getPageLanguage()->getCode(), 'page_title' => $title->getPrefixedText(),
					'old_revision_id' => $oldId, 'new_revision_id' => $newId,
					// Required by the API schema; this constant deliberately is not user data.
					'editor_username' => 'PalimpsestFlags', 'old_text' => $oldContent->getText(), 'new_text' => $newContent->getText(),
					'old_wikitext' => $oldContent->getText(), 'new_wikitext' => $newContent->getText(), 'ref_urls' => [],
				];
				$url = rtrim( (string)$config->get( 'PalimpsestFlagsApiUrl' ), '/' ) . '/api/v1/audit-diff';
				$request = $services->getHttpRequestFactory()->create( $url, [
					'method' => 'POST', 'postData' => json_encode( $payload, JSON_THROW_ON_ERROR ),
					'timeout' => max( 1, (int)$config->get( 'PalimpsestFlagsTimeout' ) ),
				], __METHOD__ );
				// HttpRequestFactory::create() has no headers option; set them on the request.
				$request->setHeader( 'Content-Type', 'application/json' );
				$request->setHeader( 'Accept', 'application/json' );
				$status = $request->execute();
				if ( !$status->isOK() ) {
					$result = $this->error( 'audit-request-failed' );
				} else {
					$body = json_decode( $request->getContent(), true, 512, JSON_THROW_ON_ERROR );
					$result = [ 'status' => 'ok', 'flags' => is_array( $body['flags'] ?? null ) ? $body['flags'] : [],
						'partial' => (bool)( $body['partial'] ?? false ), 'error' => null ];
				}
			}
		} catch ( Throwable $e ) {
			$result = $this->error( $e instanceof JsonException ? 'invalid-audit-response' : 'audit-unavailable' );
		}
		$cache->set( $key, $result, $result['status'] === 'ok' ? self::CACHE_TTL : self::ERROR_CACHE_TTL );
		$this->respond( $result );
	}

	private function error( string $error ): array { return [ 'status' => 'error', 'flags' => [], 'partial' => false, 'error' => $error ]; }
	private function respond( array $result ): void { $this->getResult()->addValue( null, 'palimpsestflags', $result ); }
	public function getAllowedParams() { return [
		'oldid' => [ ParamValidator::PARAM_TYPE => 'integer', NumericDef::PARAM_MIN => 1, ApiBase::PARAM_RANGE_ENFORCE => true, ParamValidator::PARAM_REQUIRED => true ],
		'diff' => [ ParamValidator::PARAM_TYPE => 'integer', NumericDef::PARAM_MIN => 1, ApiBase::PARAM_RANGE_ENFORCE => true, ParamValidator::PARAM_REQUIRED => true ],
	]; }
	public function isWriteMode() { return false; }
}

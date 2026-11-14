'use strict';

const test = require( 'node:test' );
const assert = require( 'node:assert/strict' );
const helpers = require( '../../infra/wiki/extensions/PalimpsestBlame/resources/helpers.js' );

function validAnalyzeFixture() {
	return {
		status: 'ready',
		page: { id: 17, title: 'Example', language: 'en', latest_revision_id: 91 },
		snapshot: { revision_id: 91, parent_id: 90, timestamp: '2026-03-15T10:00:00Z', user: 'Editor', comment: 'Updated wording', url: '/wiki/Example?oldid=91', diff_url: '/w/index.php?diff=91&oldid=90', contributions_url: '/wiki/Special:Contributions/Editor' },
		coverage: { history_complete: false, provenance_status: 'verified', reasons: [ 'Imported source history ends at this revision.' ] },
		source_text: 'A changed phrase.',
		html: '<p><span data-pb-start="2" data-pb-end="8">changed</span></p>',
		spans: [ { start: 2, end: 8, revision_id: 91, token_id: 't3', lineage_ids: [], confidence: 'certain' } ],
		revisions: [ { revision_id: 91, parent_id: 90, timestamp: '2026-03-15T10:00:00Z', user: 'Editor', comment: 'Updated wording', minor: false, source: null, url: '/wiki/Example?oldid=91', diff_url: '/w/index.php?diff=91&oldid=90', contributions_url: '/wiki/Special:Contributions/Editor' } ],
		events: [ { revision_id: 91, before: 'old phrase', after: 'changed phrase', token_ids: [], ambiguous: false } ],
		algorithm: { version: 'fixture-v1', semantics: 'last-change', limits: {} },
		mapping: { mapped_characters: 6, unmapped_reasons: [] }
	};
}

test( 'parses documented date expressions with explicit UTC boundaries', () => {
	assert.deepEqual( helpers.interpretDateQuery( 'As of 15 March 2026' ), {
		mode: 'asof', from: null, to: '2026-03-15T23:59:59Z',
		rule: 'Latest revision at or before this UTC day-end.'
	} );
	assert.deepEqual( helpers.interpretDateQuery( 'Latest version before 1 April 2026' ), {
		mode: 'before', from: null, to: '2026-04-01T00:00:00Z',
		rule: 'Latest revision strictly before this UTC day begins.'
	} );
	const range = helpers.interpretDateQuery( 'Between 1 February and 31 March 2026' );
	assert.equal( range.from, '2026-02-01T00:00:00Z' );
	assert.equal( range.to, '2026-03-31T23:59:59Z' );
	assert.equal( range.mode, 'range' );
} );

test( 'rejects invalid dates, reversed ranges, and unsupported phrasing', () => {
	assert.throws( () => helpers.interpretDateQuery( 'As of 29 February 2025' ), /real calendar date/ );
	assert.throws( () => helpers.interpretDateQuery( 'Between 31 March and 1 February 2026' ), /must not be after/ );
	assert.throws( () => helpers.interpretDateQuery( 'around March 2026' ), /Try “As of/ );
} );

test( 'manual bounds preserve explicit UTC and reject reversed or malformed controls', () => {
	assert.deepEqual( helpers.manualDateQuery( 'range', '2026-02-01T12:30', '2026-02-01T13:45' ), {
		mode: 'range', from: '2026-02-01T12:30:00Z', to: '2026-02-01T13:45:59Z',
		rule: 'Edits in this inclusive UTC range, newest first.'
	} );
	assert.throws( () => helpers.manualDateQuery( 'range', '2026-03-01T00:00', '2026-02-01T23:59' ), /must not be after/ );
	assert.throws( () => helpers.manualDateQuery( 'range', '2026-02-01T12:99', '2026-02-01T13:00' ), /valid UTC hour/ );
	assert.throws( () => helpers.manualDateQuery( 'unknown', '2026-02-01T00:00', '2026-02-01T23:59' ), /Choose as-of/ );
	assert.throws( () => helpers.manualDateQuery( 'asof', '', '' ), /Enter both date and time/ );
} );

test( 'accepts a contract-valid analyze fixture, then reports snapshot and schema defects distinctly', () => {
	const fixture = validAnalyzeFixture();
	assert.equal( helpers.validateAnalyzeResponse( fixture, 91 ), null, 'ordinary fixture must pass the response contract first' );
	assert.match( helpers.validateAnalyzeResponse( fixture, 92 ), /different revisions/ );

	const missingCoverage = validAnalyzeFixture();
	delete missingCoverage.coverage.history_complete;
	assert.match( helpers.validateAnalyzeResponse( missingCoverage, 91 ), /required source, mapping, history, or coverage/ );

	const badOffset = validAnalyzeFixture();
	badOffset.spans[ 0 ].start = -1;
	assert.match( helpers.validateAnalyzeResponse( badOffset, 91 ), /invalid UTF-16 source span/ );
} );

test( 'safe URL filter rejects executable schemes and indexes local revision identities', () => {
	assert.equal( helpers.safeHttpUrl( 'javascript:alert(1)' ), null );
	assert.equal( helpers.safeHttpUrl( 'https://example.org/wiki/Page' ), 'https://example.org/wiki/Page' );
	const fixture = validAnalyzeFixture();
	assert.equal( helpers.revisionIndex( fixture ).get( '91' ).parent_id, 90 );
} );

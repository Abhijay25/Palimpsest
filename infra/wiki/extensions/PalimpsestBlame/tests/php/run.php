<?php
declare( strict_types = 1 );

require_once __DIR__ . '/../../includes/Attribution/SourceTokenizer.php';
require_once __DIR__ . '/../../includes/Attribution/AttributionEngine.php';
require_once __DIR__ . '/../../includes/Attribution/ParsoidTextMapper.php';
require_once __DIR__ . '/../../includes/Attribution/ParsoidLinkNormalizer.php';
require_once __DIR__ . '/../../includes/Attribution/AttributionSpanCompactor.php';
require_once __DIR__ . '/../../includes/Attribution/SelectionEventFilter.php';
require_once __DIR__ . '/../../includes/Api/UtcDateBoundParser.php';

use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionEngine;
use MediaWiki\Extension\PalimpsestBlame\Attribution\SourceTokenizer;
use MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidTextMapper;
use MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidLinkNormalizer;
use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionSpanCompactor;
use MediaWiki\Extension\PalimpsestBlame\Attribution\SelectionEventFilter;
use MediaWiki\Extension\PalimpsestBlame\Api\UtcDateBoundParser;

function check( bool $condition, string $message ): void {
	if ( !$condition ) { fwrite( STDERR, "FAIL: $message\n" ); exit( 1 ); }
}

$engine = new AttributionEngine();

// Ordinary cross-contributor sentence: unchanged final token stays on its original revision.
$ordinary = $engine->analyze( [
	[ 'id' => 10, 'text' => 'A bright fox waits.' ],
	[ 'id' => 11, 'text' => 'A swift fox waits.' ],
] );
$fox = array_values( array_filter( $ordinary['tokens'], static fn ( $t ) => $t['text'] === 'fox' ) )[0];
check( $fox['revision_id'] === 10, 'unchanged wording keeps last-change revision' );
check( $ordinary['events'][1]['before'] === 'bright', 'replacement event contains exact old token' );
check( $ordinary['events'][1]['after'] === 'swift', 'replacement event contains exact new token' );
$wholeSecondBound = UtcDateBoundParser::parse( '2026-11-14T07:05:26Z', false );
check( $wholeSecondBound !== null && gmdate( 'Y-m-d\TH:i:s\Z', $wholeSecondBound ) === '2026-11-14T07:05:26Z', 'whole-second ISO bounds parse at exact UTC seconds' );
check( UtcDateBoundParser::parse( '2026-11-14T07:05:26.500Z', false ) === null, 'fractional-second bound is rejected instead of truncated' );
check( UtcDateBoundParser::parse( '2026-11-14T08:05:26+01:00', false ) === $wholeSecondBound, 'whole-second timezone offsets preserve the same instant' );
check( UtcDateBoundParser::parse( '2026-11-14T07:05:26+01:99', false ) === null && UtcDateBoundParser::parse( '2026-11-14T07:05:26+25:00', false ) === null, 'invalid timezone offsets remain rejected' );
$startOfDay = UtcDateBoundParser::parse( '2026-11-14', false );
$endOfDay = UtcDateBoundParser::parse( '2026-11-14', true );
check( $startOfDay !== null && $endOfDay === $startOfDay + 86399, 'date-only bounds retain precise start/end-of-day behavior' );
$smallHistory = $engine->analyze( [ [ 'id' => 12, 'text' => 'small history' ], [ 'id' => 13, 'text' => 'small verified history' ] ] );
$smallTokens = $smallHistory['tokens'];
check( end( $smallTokens )['text'] === 'history', 'ordinary history below the per-revision token ceiling remains analyzable' );
$ordinarySpans = ( new AttributionSpanCompactor() )->compact( $ordinary['tokens'] );
$ordinaryLineage = array_values( array_unique( array_merge( ...array_column( $ordinary['tokens'], 'lineage_ids' ) ) ) );
$ordinarySpanLineage = array_values( array_unique( array_merge( ...array_column( $ordinarySpans, 'lineage_ids' ) ) ) );
sort( $ordinaryLineage, SORT_STRING ); sort( $ordinarySpanLineage, SORT_STRING );
check( $ordinaryLineage === $ordinarySpanLineage, 'ordinary compact spans retain the full set of token lineage IDs' );

$oversizedRevision = false;
try {
	$engine->analyze( [ [ 'id' => 14, 'text' => str_repeat( 'x ', 10001 ) ] ] );
} catch ( DomainException $e ) {
	$oversizedRevision = $e->getMessage() === 'revision-token-limit-exceeded';
}
check( $oversizedRevision, 'single-revision token ceiling rejects oversized input before allocating attribution tokens' );

// Multi-step one-token replacements retain a stable ancestry chain.
$lineage = $engine->analyze( [
	[ 'id' => 20, 'text' => 'quick fox' ],
	[ 'id' => 21, 'text' => 'swift fox' ],
	[ 'id' => 22, 'text' => 'fast fox' ],
] );
$fast = array_values( array_filter( $lineage['tokens'], static fn ( $t ) => $t['text'] === 'fast' ) )[0];
check( $fast['revision_id'] === 22, 'current replacement gets the latest last-change revision' );
check( in_array( '20:0', $fast['lineage_ids'], true ), 'multi-step replacement retains original token lineage' );
check( in_array( '20:0', $lineage['events'][1]['token_ids'], true ), 'first replacement event retains removed token identity' );

$multiLineage = $engine->analyze( [
	[ 'id' => 23, 'text' => 'fast blue fox' ],
	[ 'id' => 24, 'text' => 'slow green fox' ],
	[ 'id' => 25, 'text' => 'new quick fox' ],
] );
$quick = array_values( array_filter( $multiLineage['tokens'], static fn ( $t ) => $t['text'] === 'quick' ) )[0];
check( in_array( '23:2', $quick['lineage_ids'], true ), 'word replacement retains its aligned prior ancestry across revisions' );
check( !$quick['ambiguous'], 'unique one-to-one word replacements remain aligned' );

// A pure deletion remains connected to the selected surviving word after a later edit.
$deletion = $engine->analyze( [
	[ 'id' => 30, 'text' => 'red fox sleeps' ],
	[ 'id' => 31, 'text' => 'fox sleeps' ],
	[ 'id' => 32, 'text' => 'fox naps' ],
] );
$selectedFox = array_values( array_filter( $deletion['tokens'], static fn ( $t ) => $t['text'] === 'fox' ) )[0];
$deletedRed = $deletion['events'][1];
check( $deletedRed['before'] === 'red ', 'pure deletion preserves exact removed wording and adjacent whitespace' );
check( $deletedRed['after'] === '', 'pure deletion has empty replacement text' );
check( in_array( $selectedFox['token_id'], [ $deletedRed['left_token_id'], $deletedRed['right_token_id'] ], true ), 'deleted wording remains anchored to selected surviving phrase' );
$selectedFoxIds = array_merge( [ $selectedFox['token_id'] ], $selectedFox['lineage_ids'] );
$selectedDeletionEvents = SelectionEventFilter::filter( [ $deletedRed ], $selectedFoxIds );
check( count( $selectedDeletionEvents ) === 1 && $selectedDeletionEvents[0]['revision_id'] === 31, 'anchor-only selection retains a pure deletion beside a selected surviving word' );

// Selecting the opening phrase must not pull in later additions merely because they share an adjacent anchor.
$scopedHistory = $engine->analyze( [
	[ 'id' => 392, 'text' => 'The old station' ],
	[ 'id' => 393, 'text' => 'The old station measures coastal winds' ],
	[ 'id' => 394, 'text' => 'The old station measures coastal winds throughout each summer season.' ],
] );
$scopedTokenIds = [];
foreach ( $scopedHistory['tokens'] as $token ) {
	if ( $token['utf16_start'] < 15 && $token['utf16_end'] > 0 ) {
		$scopedTokenIds[] = $token['token_id'];
		$scopedTokenIds = array_merge( $scopedTokenIds, $token['lineage_ids'] );
	}
}
$scopedEvents = SelectionEventFilter::filter( $scopedHistory['events'], $scopedTokenIds );
check( array_column( $scopedEvents, 'revision_id' ) === [ 392 ], 'selection returns directly matching initial text without unrelated later additions' );

// UTF-16 offsets account for supplementary emoji and combining marks.
$unicode = SourceTokenizer::tokenize( "😀e\u{0301} x" );
check( $unicode[0]['utf16_start'] === 0 && $unicode[0]['utf16_end'] === 2, 'emoji uses two UTF-16 code units' );
check( $unicode[1]['utf16_start'] === 2 && $unicode[1]['utf16_end'] === 4, 'combining sequence follows exact UTF-16 offsets' );

// Duplicate text and patience-anchor fallback never assert a unique alignment.
$duplicate = $engine->analyze( [ [ 'id' => 40, 'text' => 'same same end' ], [ 'id' => 41, 'text' => 'same end' ] ] );
check( (bool)array_filter( $duplicate['tokens'], static fn ( $t ) => $t['text'] === 'same' && $t['ambiguous'] ), 'repeated text is marked ambiguous' );
$moveRevert = $engine->analyze( [
	[ 'id' => 41, 'text' => 'red marker rests; red marker waits.' ],
	[ 'id' => 42, 'text' => 'red marker waits; red marker rests.' ],
	[ 'id' => 43, 'text' => 'red marker rests; red marker waits.' ],
] );
$moveEvents = array_slice( $moveRevert['events'], 1 );
$restoredWords = array_values( array_filter( $moveRevert['tokens'], static fn ( $t ) => in_array( $t['text'], [ 'rests', 'waits' ], true ) ) );
check( count( $moveEvents ) >= 2 && !in_array( false, array_column( $moveEvents, 'ambiguous' ), true ), 'moved and reverted wording marks both edit events ambiguous' );
check( count( $restoredWords ) === 2 && !in_array( false, array_column( $restoredWords, 'ambiguous' ), true ), 'reordered words stay ambiguous after returning to their original positions' );
$numericDuplicate = $engine->analyze( [ [ 'id' => 42, 'text' => 'score 2000 2000 points' ], [ 'id' => 43, 'text' => 'score 2000 points' ] ] );
check( (bool)array_filter( $numericDuplicate['tokens'], static fn ( $t ) => $t['text'] === '2000' && $t['ambiguous'] ), 'numeric token keys remain strings during ambiguity checks' );

$stressOld = implode( ' ', array_map( static fn ( $i ) => 'old' . $i, range( 1, 250 ) ) );
$stressMiddle = implode( '-', array_map( static fn ( $i ) => 'middle' . $i, range( 1, 250 ) ) );
$stressNew = implode( '/', array_map( static fn ( $i ) => 'new' . $i, range( 1, 250 ) ) );
$stressLatest = implode( '+', array_map( static fn ( $i ) => 'latest' . $i, range( 1, 250 ) ) );
$lineageLimitReached = false;
try {
	$engine->analyze( [
		[ 'id' => 44, 'text' => $stressOld ],
		[ 'id' => 45, 'text' => $stressMiddle ],
		[ 'id' => 46, 'text' => $stressNew ],
		[ 'id' => 47, 'text' => $stressLatest ],
	] );
} catch ( DomainException $e ) {
	$lineageLimitReached = $e->getMessage() === 'lineage-derivation-reference-limit-exceeded';
}
check( $lineageLimitReached, 'large cross-gap ancestry fails explicitly before unbounded fanout' );

$phraseAnalysis = $engine->analyze( [ [ 'id' => 70, 'text' => 'old red blue fox' ], [ 'id' => 71, 'text' => 'new-fast-dog' ] ] );
$phraseTokens = $phraseAnalysis['tokens'];
$phraseSpans = ( new AttributionSpanCompactor() )->compact( $phraseTokens );
$legacyPhraseSpans = array_map( static function ( array $token ): array {
	$start = $token['utf16_start'];
	$end = $token['utf16_end'];
	unset( $token['start'], $token['end'], $token['utf16_start'], $token['utf16_end'] );
	$token['start'] = $start;
	$token['end'] = $end;
	$token['confidence'] = $token['ambiguous'] ? 'ambiguous' : 'aligned';
	return $token;
}, $phraseTokens );
$fastToken = array_values( array_filter( $phraseTokens, static fn ( $t ) => $t['text'] === 'fast' ) )[0];
$partStart = $fastToken['utf16_start'] + 1;
$partEnd = $fastToken['utf16_end'] - 1;
$selectedPhraseTokens = array_values( array_filter( $phraseSpans[0]['token_ranges'], static fn ( $r ) => $r[0] < $partEnd && $r[1] > $partStart ) );
check( count( $phraseSpans ) === 1 && count( $phraseSpans[0]['token_ranges'] ) === count( $phraseTokens ), 'same-owner phrase spans compact while retaining every stable token range' );
check( count( $selectedPhraseTokens ) === 1 && $selectedPhraseTokens[0][2] === $fastToken['token_id'], 'partial selection inside a compact phrase resolves only its exact token ID' );
$phraseLineage = array_values( array_unique( array_merge( ...array_column( $phraseTokens, 'lineage_ids' ) ) ) );
$groupLineage = $phraseSpans[0]['lineage_ids'];
sort( $phraseLineage, SORT_STRING ); sort( $groupLineage, SORT_STRING );
check( $phraseLineage === $groupLineage && in_array( '70:0', $groupLineage, true ), 'merged phrase lineage contains the owner ancestry and every member token ID without omissions' );
check( strlen( json_encode( $phraseSpans, JSON_THROW_ON_ERROR ) ) < strlen( json_encode( $legacyPhraseSpans, JSON_THROW_ON_ERROR ) ), 'shared ancestry serialization shrinks when adjacent spans are coalesced' );

$longOld = implode( ' ', array_map( static fn ( $i ) => 'word' . $i, range( 1, 900 ) ) );
$longNew = preg_replace( '/word450/', 'changed450', $longOld );
$longResult = $engine->analyze( [ [ 'id' => 50, 'text' => $longOld ], [ 'id' => 51, 'text' => $longNew ] ] );
check( count( $longResult['tokens'] ) > 900, 'long mostly unchanged history does not allocate a quadratic full-page matrix' );
check( count( $longResult['events'] ) >= 2, 'long edit exposes a bounded changed-region event' );

$failedInvalidUtf8 = false;
try { SourceTokenizer::tokenize( "\xFF" ); } catch ( DomainException ) { $failedInvalidUtf8 = true; }
check( $failedInvalidUtf8, 'invalid UTF-8 fails explicitly instead of producing an empty history' );

// DSR mapper proves visible bold and piped-link labels by exact source slice, retaining the native tags.
$source = "A '''bold''' and [[Target|label]]";
$boldStart = strpos( $source, "'''bold'''" );
$linkStart = strpos( $source, '[[Target|label]]' );
$linkEnd = $linkStart + strlen( '[[Target|label]]' );
$tokens = $engine->analyze( [ [ 'id' => 60, 'text' => $source ] ] )['tokens'];
$mapped = ( new ParsoidTextMapper() )->map(
	'<p id="p">A <b id="b">bold</b> and <a id="l">label</a></p>',
	$source,
	[ 'p' => [ 'dsr' => [ 0, strlen( $source ), 0, 0 ] ], 'b' => [ 'dsr' => [ $boldStart, $boldStart + 10, 3, 3 ] ], 'l' => [ 'dsr' => [ $linkStart, $linkEnd, 9, 2 ] ] ],
	$tokens
);
check( $mapped['mapped_characters'] === strlen( 'A bold and label' ), 'only visible text is marked mapped; source markup remains unmapped' );
check( str_contains( $mapped['html'], '<b id="b"><span data-pb-start=' ), 'bold formatting survives with an exact annotated text span' );
check( str_contains( $mapped['html'], '<a id="l"><span data-pb-start=' ), 'piped link survives with its exact label span' );

// Parsoid's ./Title links must work when its HTML is inserted into action=blame.
$normalizedLinks = ( new ParsoidLinkNormalizer() )->normalize(
	'<a href="./Finnish_Rally_Championship?action=edit&amp;redlink=1#History">missing page</a> <a href="https://example.org/">external</a>',
	static fn ( string $text ): string => '/wiki/' . rawurlencode( str_replace( ' ', '_', $text ) )
);
check( str_contains( $normalizedLinks, 'href="/wiki/Finnish_Rally_Championship?action=edit&amp;redlink=1#History"' ), 'relative internal link becomes a working local title URL and preserves query and fragment' );
check( str_contains( $normalizedLinks, 'href="https://example.org/"' ), 'external links remain unchanged' );
$queryStyleLink = ( new ParsoidLinkNormalizer() )->normalize(
	'<a href="./Finnish_Rally_Championship?action=edit&amp;redlink=1#History">missing page</a>',
	static fn ( string $text ): string => '/index.php?title=' . rawurlencode( str_replace( ' ', '_', $text ) )
);
check( str_contains( $queryStyleLink, 'href="/index.php?title=Finnish_Rally_Championship&amp;action=edit&amp;redlink=1#History"' ), 'query-style local URLs append Parsoid parameters with ampersand and preserve redlink navigation' );

$generatedSource = 'before {{T}}';
$generatedTokens = $engine->analyze( [ [ 'id' => 61, 'text' => $generatedSource ] ] )['tokens'];
$generated = ( new ParsoidTextMapper() )->map(
	'<p id="p">before <span id="t" about="#mwt1" typeof="mw:Transclusion">generated</span></p>',
	$generatedSource,
	[ 'p' => [ 'dsr' => [ 0, strlen( $generatedSource ), 0, 0 ] ], 't' => [ 'dsr' => [ 7, strlen( $generatedSource ), 0, 0 ] ] ],
	$generatedTokens
);
check( in_array( 'generated-or-transcluded-content', $generated['unmapped_reasons'], true ), 'transcluded content is explicitly unmapped' );
check( !str_contains( $generated['html'], 'typeof="mw:Transclusion"><span' ), 'unproved generated text receives no attribution span' );

$generatedAncestor = ( new ParsoidTextMapper() )->map(
	'<div id="g" about="#mwt9"><p id="p">extension output</p></div>',
	'{{Extension}}',
	[ 'p' => [ 'dsr' => [ 0, 12, 0, 0 ] ] ],
	$engine->analyze( [ [ 'id' => 62, 'text' => '{{Extension}}' ] ] )['tokens']
);
check( in_array( 'generated-or-transcluded-content', $generatedAncestor['unmapped_reasons'], true ), 'generated ancestors suppress otherwise mappable paragraph descendants' );

$extension = ( new ParsoidTextMapper() )->map(
	'<p id="p"><span id="e" typeof="mw:Extension/ref">1</span></p>',
	'<ref>x</ref>',
	[ 'p' => [ 'dsr' => [ 0, 12, 0, 0 ] ], 'e' => [ 'dsr' => [ 0, 12, 0, 0 ] ] ],
	$engine->analyze( [ [ 'id' => 63, 'text' => '<ref>x</ref>' ] ] )['tokens']
);
check( in_array( 'generated-or-transcluded-content', $extension['unmapped_reasons'], true ), 'slash-qualified extension output remains unmapped' );

echo "PASS: 26 isolated attribution, DSR, selection, date-bound, and link fixtures\n";

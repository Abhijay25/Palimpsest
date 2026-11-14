<?php
declare( strict_types = 1 );

require_once __DIR__ . '/../../includes/Attribution/SourceTokenizer.php';
require_once __DIR__ . '/../../includes/Attribution/AttributionEngine.php';
require_once __DIR__ . '/../../includes/Attribution/ParsoidTextMapper.php';
require_once __DIR__ . '/../../includes/Attribution/ParsoidLinkNormalizer.php';

use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionEngine;
use MediaWiki\Extension\PalimpsestBlame\Attribution\SourceTokenizer;
use MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidTextMapper;
use MediaWiki\Extension\PalimpsestBlame\Attribution\ParsoidLinkNormalizer;

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

// UTF-16 offsets account for supplementary emoji and combining marks.
$unicode = SourceTokenizer::tokenize( "😀e\u{0301} x" );
check( $unicode[0]['utf16_start'] === 0 && $unicode[0]['utf16_end'] === 2, 'emoji uses two UTF-16 code units' );
check( $unicode[1]['utf16_start'] === 2 && $unicode[1]['utf16_end'] === 4, 'combining sequence follows exact UTF-16 offsets' );

// Duplicate text and patience-anchor fallback never assert a unique alignment.
$duplicate = $engine->analyze( [ [ 'id' => 40, 'text' => 'same same end' ], [ 'id' => 41, 'text' => 'same end' ] ] );
check( (bool)array_filter( $duplicate['tokens'], static fn ( $t ) => $t['text'] === 'same' && $t['ambiguous'] ), 'repeated text is marked ambiguous' );

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

echo "PASS: 14 isolated attribution, DSR, and link fixtures\n";

<?php
declare( strict_types = 1 );

// Offline algorithm comparison; no database, network, or generated repository state.
$base = dirname( __DIR__ ) . '/infra/wiki/extensions/PalimpsestBlame/includes/Attribution/';
require_once $base . 'SourceTokenizer.php';
require_once $base . 'AttributionEngine.php';

use MediaWiki\Extension\PalimpsestBlame\Attribution\AttributionEngine;
use MediaWiki\Extension\PalimpsestBlame\Attribution\SourceTokenizer;

/** Whole-document dynamic-programming LCS baseline, under the same cell budget. */
function baseline( array $old, array $new ): array {
	$n = count( $old ); $m = count( $new );
	if ( $n * $m > AttributionEngine::MAX_DIFF_CELLS ) {
		return [ 'status' => 'budget-exceeded', 'cells' => $n * $m ];
	}
	$dp = array_fill( 0, $n + 1, array_fill( 0, $m + 1, 0 ) );
	for ( $i = $n - 1; $i >= 0; $i-- ) {
		for ( $j = $m - 1; $j >= 0; $j-- ) {
			$dp[$i][$j] = $old[$i] === $new[$j]
				? 1 + $dp[$i + 1][$j + 1] : max( $dp[$i + 1][$j], $dp[$i][$j + 1] );
		}
	}
	$preserved = []; $i = 0; $j = 0;
	while ( $i < $n && $j < $m ) {
		if ( $old[$i] === $new[$j] ) { $preserved[$j++] = true; $i++; }
		elseif ( $dp[$i + 1][$j] >= $dp[$i][$j + 1] ) { $i++; }
		else { $j++; }
	}
	return [ 'status' => 'ready', 'preserved_indexes' => array_keys( $preserved ), 'cells' => $n * $m ];
}

$small = implode( ' ', array_map( static fn ( $i ) => 'word' . $i, range( 1, 100 ) ) );
$large = implode( ' ', array_map( static fn ( $i ) => 'word' . $i, range( 1, 900 ) ) );
$cases = [
	'small-sparse-edit' => [ $small, str_replace( 'word50 ', 'changed50 ', $small ), 'word99', 'changed50' ],
	'large-sparse-edit' => [ $large, str_replace( 'word450 ', 'changed450 ', $large ), 'word899', 'changed450' ],
	'large-dispersed-edit' => [ $large, str_replace( [ 'word1 ', 'word900' ], [ 'changed1 ', 'changed900' ], $large ), 'word899', 'changed900' ],
];
$report = [ 'php' => PHP_VERSION, 'cell_budget' => AttributionEngine::MAX_DIFF_CELLS, 'cases' => [] ];
foreach ( $cases as $name => [ $old, $new, $unchanged, $changed ] ) {
	$a = array_column( SourceTokenizer::tokenize( $old ), 'text' );
	$b = array_column( SourceTokenizer::tokenize( $new ), 'text' );
	$t0 = hrtime( true ); $plain = baseline( $a, $b ); $plainMs = ( hrtime( true ) - $t0 ) / 1e6;
	$t0 = hrtime( true );
	$analysis = ( new AttributionEngine() )->analyze( [ [ 'id' => 1, 'text' => $old ], [ 'id' => 2, 'text' => $new ] ] );
	$selectedMs = ( hrtime( true ) - $t0 ) / 1e6;
	$actual = [];
	foreach ( $analysis['tokens'] as $token ) { $actual[$token['text']] = $token['revision_id']; }
	if ( ( $actual[$unchanged] ?? null ) !== 1 || ( $actual[$changed] ?? null ) !== 2 ) {
		throw new RuntimeException( 'Selected algorithm failed independent unchanged/changed attribution expectations.' );
	}
	if ( $plain['status'] === 'ready' ) {
		$indexes = array_flip( $plain['preserved_indexes'] );
		foreach ( $b as $index => $text ) {
			if ( ( $text === $unchanged && !isset( $indexes[$index] ) ) || ( $text === $changed && isset( $indexes[$index] ) ) ) {
				throw new RuntimeException( 'Baseline failed independent preservation expectations.' );
			}
		}
	}
	$report['cases'][$name] = [
		'source_bytes' => [ strlen( $old ), strlen( $new ) ], 'tokens' => [ count( $a ), count( $b ) ],
		'whole_document_lcs' => [ 'status' => $plain['status'], 'cells' => $plain['cells'], 'elapsed_ms' => round( $plainMs, 3 ) ],
		'edge_trimmed_lcs_with_unique_anchor_fallback' => [ 'status' => 'ready', 'elapsed_ms' => round( $selectedMs, 3 ), 'ambiguous_tokens' => count( array_filter( $analysis['tokens'], static fn ( $t ) => $t['ambiguous'] ) ), 'expectations' => 'unchanged revision1; changed revision2' ],
	];
}
$report['peak_process_bytes'] = memory_get_peak_usage( true );
$report['limits'] = 'Single-process offline samples; baseline times exclude tokenization, selected times include it. Peak is combined, not per-algorithm. No database or production throughput inference. Dispersed changes exercise the conservative, ambiguous unique-anchor fallback.';
echo json_encode( $report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR ) . "\n";

<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

use DomainException;

/** Last-change attribution over source tokens; alignment ambiguity is exposed, not resolved by guess. */
final class AttributionEngine {
	public const VERSION = 'lcs-anchor-v1';
	public const MAX_DIFF_CELLS = 250000;

	/** @param list<array{id:int,text:string}> $history Oldest first. */
	public function analyze( array $history ): array {
		if ( !$history ) { throw new DomainException( 'History is empty' ); }
		$current = [];
		$events = [];
		foreach ( $history as $revisionIndex => $revision ) {
			$next = SourceTokenizer::tokenize( $revision['text'] );
			if ( $revisionIndex === 0 ) {
				foreach ( $next as $i => &$token ) {
					$id = $revision['id'] . ':' . $i;
					$token += [ 'revision_id' => $revision['id'], 'introduced_revision_id' => $revision['id'], 'lineage_ids' => [ $id ], 'token_id' => $id, 'ambiguous' => false ];
				}
				unset( $token );
				$current = $next;
				$events[] = self::event( $revision['id'], 0, 0, [], $next, false, null, null );
				continue;
			}

			[ $matches, $anchorFallback ] = self::lcsMatches( array_column( $current, 'text' ), array_column( $next, 'text' ) );
			$ambiguousValues = self::ambiguousValues( array_column( $current, 'text' ), array_column( $next, 'text' ) );
			$rebuilt = [];
			$oldCursor = 0;
			$newCursor = 0;
			$parentId = $history[$revisionIndex - 1]['id'];
			foreach ( $matches as [ $oldIndex, $newIndex ] ) {
				if ( $oldIndex > $oldCursor || $newIndex > $newCursor ) {
					$oldGap = array_slice( $current, $oldCursor, $oldIndex - $oldCursor );
					$newGap = array_slice( $next, $newCursor, $newIndex - $newCursor );
					$newGap = self::attributeNewTokens( $newGap, $revision['id'], $newCursor, $ambiguousValues, $oldGap );
					$left = self::nearestWordAnchor( $rebuilt, count( $rebuilt ) - 1, -1 );
					$right = self::nearestWordAnchor( $current, $oldIndex, 1 );
					$ambiguous = $anchorFallback || self::hasAmbiguity( $newGap ) || self::hasAmbiguity( $oldGap ) || ( count( $oldGap ) > 1 && count( $newGap ) > 0 );
					$events[] = self::event( $revision['id'], $parentId, $current[$oldCursor]['utf16_start'] ?? 0, $oldGap, $newGap, $ambiguous, $left, $right );
					array_push( $rebuilt, ...$newGap );
				}
				$matched = $current[$oldIndex];
				$matched['start'] = $next[$newIndex]['start'];
				$matched['end'] = $next[$newIndex]['end'];
				$matched['utf16_start'] = $next[$newIndex]['utf16_start'];
				$matched['utf16_end'] = $next[$newIndex]['utf16_end'];
				$matched['ambiguous'] = $matched['ambiguous'] || isset( $ambiguousValues[$matched['text']] ) || $anchorFallback;
				$rebuilt[] = $matched;
				$oldCursor = $oldIndex + 1;
				$newCursor = $newIndex + 1;
			}
			if ( $oldCursor < count( $current ) || $newCursor < count( $next ) ) {
				$oldGap = array_slice( $current, $oldCursor );
				$newGap = array_slice( $next, $newCursor );
				$newGap = self::attributeNewTokens( $newGap, $revision['id'], $newCursor, $ambiguousValues, $oldGap );
				$left = self::nearestWordAnchor( $rebuilt, count( $rebuilt ) - 1, -1 );
				$ambiguous = $anchorFallback || self::hasAmbiguity( $newGap ) || self::hasAmbiguity( $oldGap ) || ( count( $oldGap ) > 1 && count( $newGap ) > 0 );
				$events[] = self::event( $revision['id'], $parentId, $current[$oldCursor]['utf16_start'] ?? ( $current ? end( $current )['utf16_end'] : 0 ), $oldGap, $newGap, $ambiguous, $left, null );
				array_push( $rebuilt, ...$newGap );
			}
			$current = $rebuilt;
		}
		return [
			'tokens' => $current,
			'events' => $events,
			'algorithm' => [
				'version' => self::VERSION,
				'semantics' => 'Unchanged LCS-aligned tokens retain their last-change revision. New tokens receive the current revision. Replacements inherit all removed-token lineage in their unmatched gap; non-one-to-one associations and patience-anchor fallback are marked ambiguous. Deletions retain stable removed-token IDs and neighboring anchors. This does not prove unique authorship.',
				'limits' => [ 'maximum_lcs_cells_per_pair' => self::MAX_DIFF_CELLS, 'fallback' => 'unique-token patience anchors; resulting preserved tokens are ambiguous' ],
			],
		];
	}

	private static function attributeNewTokens( array $tokens, int $revisionId, int $offset, array $ambiguousValues, array $removed ): array {
		$ancestors = [];
		foreach ( $removed as $oldToken ) {
			$ancestors[] = $oldToken['token_id'];
			array_push( $ancestors, ...$oldToken['lineage_ids'] );
		}
		$ancestors = array_values( array_unique( $ancestors ) );
		$inheritOne = count( $tokens ) === 1 && count( $removed ) === 1;
		foreach ( $tokens as $i => &$token ) {
			$id = $revisionId . ':' . ( $offset + $i );
			$token += [
				'revision_id' => $revisionId,
				'introduced_revision_id' => $revisionId,
				'lineage_ids' => array_values( array_unique( [ ...$ancestors, $id ] ) ),
				'token_id' => $id,
				'ambiguous' => isset( $ambiguousValues[$token['text']] ) || ( $removed && !$inheritOne ),
			];
		}
		unset( $token );
		return $tokens;
	}

	private static function hasAmbiguity( array $tokens ): bool {
		foreach ( $tokens as $token ) { if ( $token['ambiguous'] ) { return true; } }
		return false;
	}

	private static function nearestWordAnchor( array $tokens, int $at, int $step ): ?string {
		for ( $i = $at; $i >= 0 && $i < count( $tokens ); $i += $step ) {
			if ( preg_match( '/\S/u', $tokens[$i]['text'] ) ) { return $tokens[$i]['token_id']; }
		}
		return null;
	}

	private static function event( int $revisionId, int $parentId, int $oldStart, array $oldTokens, array $newTokens, bool $ambiguous, ?string $left, ?string $right ): array {
		$removedIds = [];
		foreach ( $oldTokens as $token ) { $removedIds[] = $token['token_id']; array_push( $removedIds, ...$token['lineage_ids'] ); }
		$ids = array_values( array_unique( [ ...$removedIds, ...array_column( $newTokens, 'token_id' ) ] ) );
		return [
			'revision_id' => $revisionId,
			'before' => implode( '', array_column( $oldTokens, 'text' ) ),
			'after' => implode( '', array_column( $newTokens, 'text' ) ),
			'token_ids' => $ids,
			'added_token_ids' => array_column( $newTokens, 'token_id' ),
			'removed_token_ids' => array_column( $oldTokens, 'token_id' ),
			'left_token_id' => $left,
			'right_token_id' => $right,
			'ambiguous' => $ambiguous,
			'reason' => $ambiguous ? 'Token alignment or replacement lineage is ambiguous.' : null,
			'old_start' => $oldTokens ? $oldTokens[0]['utf16_start'] : $oldStart,
			'old_end' => $oldTokens ? end( $oldTokens )['utf16_end'] : $oldStart,
			'new_start' => $newTokens ? $newTokens[0]['utf16_start'] : null,
			'new_end' => $newTokens ? end( $newTokens )['utf16_end'] : null,
			'parent_revision_id' => $parentId,
		];
	}

	/** Trim common edges; use LCS for the bounded middle and unique anchors for large middle regions. */
	private static function lcsMatches( array $a, array $b ): array {
		$n = count( $a ); $m = count( $b );
		$prefix = 0;
		while ( $prefix < $n && $prefix < $m && $a[$prefix] === $b[$prefix] ) { $prefix++; }
		$suffix = 0;
		while ( $suffix < $n - $prefix && $suffix < $m - $prefix && $a[$n - $suffix - 1] === $b[$m - $suffix - 1] ) { $suffix++; }
		$am = array_slice( $a, $prefix, $n - $prefix - $suffix );
		$bm = array_slice( $b, $prefix, $m - $prefix - $suffix );
		$anchorFallback = count( $am ) * count( $bm ) > self::MAX_DIFF_CELLS;
		if ( $anchorFallback ) {
			$middle = self::uniqueAnchorMatches( $am, $bm );
			if ( !$middle ) { throw new DomainException( 'The changed region exceeds the bounded diff work limit and has no safe unique anchors.' ); }
		} else {
			$middle = self::computeLcsMatches( $am, $bm );
		}
		$matches = [];
		for ( $i = 0; $i < $prefix; $i++ ) { $matches[] = [ $i, $i ]; }
		foreach ( $middle as [ $i, $j ] ) { $matches[] = [ $prefix + $i, $prefix + $j ]; }
		for ( $i = $suffix; $i > 0; $i-- ) { $matches[] = [ $n - $i, $m - $i ]; }
		return [ $matches, $anchorFallback ];
	}

	private static function computeLcsMatches( array $a, array $b ): array {
		$n = count( $a ); $m = count( $b );
		$rows = array_fill( 0, $n + 1, null );
		$rows[$n] = array_fill( 0, $m + 1, 0 );
		for ( $i = $n - 1; $i >= 0; $i-- ) {
			$row = array_fill( 0, $m + 1, 0 );
			for ( $j = $m - 1; $j >= 0; $j-- ) { $row[$j] = $a[$i] === $b[$j] ? 1 + $rows[$i + 1][$j + 1] : max( $rows[$i + 1][$j], $row[$j + 1] ); }
			$rows[$i] = $row;
		}
		$matches = [];
		for ( $i = 0, $j = 0; $i < $n && $j < $m; ) {
			if ( $a[$i] === $b[$j] ) { $matches[] = [ $i++, $j++ ]; }
			elseif ( $rows[$i + 1][$j] >= $rows[$i][$j + 1] ) { $i++; }
			else { $j++; }
		}
		return $matches;
	}

	private static function uniqueAnchorMatches( array $a, array $b ): array {
		$ca = array_count_values( $a ); $cb = array_count_values( $b ); $positions = [];
		foreach ( $b as $j => $value ) { if ( ( $cb[$value] ?? 0 ) === 1 ) { $positions[$value] = $j; } }
		$sequence = [];
		foreach ( $a as $i => $value ) { if ( ( $ca[$value] ?? 0 ) === 1 && isset( $positions[$value] ) ) { $sequence[] = [ $i, $positions[$value] ]; } }
		$tails = []; $tailIndexes = []; $previous = array_fill( 0, count( $sequence ), -1 );
		foreach ( $sequence as $k => [ , $j ] ) {
			$low = 0; $high = count( $tails );
			while ( $low < $high ) { $mid = intdiv( $low + $high, 2 ); if ( $tails[$mid] < $j ) { $low = $mid + 1; } else { $high = $mid; } }
			if ( $low > 0 ) { $previous[$k] = $tailIndexes[$low - 1]; }
			$tails[$low] = $j; $tailIndexes[$low] = $k;
		}
		if ( !$tailIndexes ) { return []; }
		$out = []; $k = $tailIndexes[count( $tailIndexes ) - 1];
		while ( $k >= 0 ) { $out[] = $sequence[$k]; $k = $previous[$k]; }
		return array_reverse( $out );
	}

	private static function ambiguousValues( array $a, array $b ): array {
		$ca = array_count_values( $a ); $cb = array_count_values( $b ); $out = [];
		foreach ( $ca as $rawValue => $count ) {
			$value = (string)$rawValue;
			if ( preg_match( '/[\p{L}\p{N}\p{M}]/u', $value ) === 1 && ( $count > 1 || ( $cb[$value] ?? 0 ) > 1 ) && ( $cb[$value] ?? 0 ) > 0 ) {
				$out[$value] = true;
			}
		}
		return $out;
	}
}

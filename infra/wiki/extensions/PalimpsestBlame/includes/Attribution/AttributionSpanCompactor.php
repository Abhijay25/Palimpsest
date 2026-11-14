<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

/** Coalesces adjacent API spans only when their owner and inherited ancestry are identical. */
final class AttributionSpanCompactor {
	/** @param list<array> $tokens @return list<array> */
	public function compact( array $tokens ): array {
		$spans = [];
		$group = null;
		foreach ( $tokens as $token ) {
			$ancestors = array_values( array_filter( $token['lineage_ids'], static fn ( $id ) => $id !== $token['token_id'] ) );
			$start = $token['utf16_start'];
			$end = $token['utf16_end'];
			$canAppend = $group !== null &&
				$group['revision_id'] === $token['revision_id'] &&
				$group['introduced_revision_id'] === $token['introduced_revision_id'] &&
				$group['ambiguous'] === $token['ambiguous'] &&
				$group['lineage_ids'] === $ancestors &&
				$group['end'] === $start;
			if ( !$canAppend ) {
				if ( $group !== null ) { $spans[] = self::finish( $group ); }
				$group = [
					'start' => $start,
					'end' => $end,
					'revision_id' => $token['revision_id'],
					'introduced_revision_id' => $token['introduced_revision_id'],
					'token_id' => $token['token_id'],
					'token_ranges' => [ [ $start, $end, $token['token_id'] ] ],
					'lineage_ids' => $ancestors,
					'ambiguous' => $token['ambiguous'],
					'text' => $token['text'],
				];
				continue;
			}
			$group['end'] = $end;
			$group['token_ranges'][] = [ $start, $end, $token['token_id'] ];
			$group['text'] .= $token['text'];
		}
		if ( $group !== null ) { $spans[] = self::finish( $group ); }
		return $spans;
	}

	private static function finish( array $group ): array {
		if ( count( $group['token_ranges'] ) === 1 ) {
			$group['lineage_ids'][] = $group['token_id'];
		} else {
			$group['token_ranges'] = array_values( $group['token_ranges'] );
		}
		$group['confidence'] = $group['ambiguous'] ? 'ambiguous' : 'aligned';
		return $group;
	}
}

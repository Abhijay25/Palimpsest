<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

/** Selects directly related events, using anchors only to retain pure deletions. */
final class SelectionEventFilter {
	/** @param list<array> $events @param list<string> $selectedTokenIds @return list<array> */
	public static function filter( array $events, array $selectedTokenIds ): array {
		$selected = array_fill_keys( $selectedTokenIds, true );
		return array_values( array_filter( $events, static function ( array $event ) use ( $selected ): bool {
			foreach ( $event['token_ids'] ?? [] as $id ) {
				if ( isset( $selected[$id] ) ) { return true; }
			}
			if ( ( $event['before'] ?? '' ) === '' || ( $event['after'] ?? '' ) !== '' ) { return false; }
			return isset( $selected[$event['left_token_id'] ?? ''] ) || isset( $selected[$event['right_token_id'] ?? ''] );
		} ) );
	}
}

<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Api;

use DateTimeImmutable;
use DateTimeZone;
use Throwable;

/** Parses prototype date bounds at whole-second precision. */
final class UtcDateBoundParser {
	public static function parse( string $value, bool $endOfDay ): ?int {
		if ( preg_match( '/^\d{4}-\d{2}-\d{2}$/', $value ) ) {
			[ $year, $month, $day ] = array_map( 'intval', explode( '-', $value ) );
			if ( !checkdate( $month, $day, $year ) ) { return null; }
			$dt = DateTimeImmutable::createFromFormat( '!Y-m-d', $value, new DateTimeZone( 'UTC' ) );
			if ( !$dt || $dt->format( 'Y-m-d' ) !== $value ) { return null; }
			return $endOfDay ? $dt->getTimestamp() + 86399 : $dt->getTimestamp();
		}
		if ( !preg_match( '/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:Z|[+-]\d{2}:\d{2})$/', $value, $parts ) ) {
			return null;
		}
		if ( !checkdate( (int)$parts[2], (int)$parts[3], (int)$parts[1] ) || (int)$parts[4] > 23 || (int)$parts[5] > 59 || (int)$parts[6] > 59 ) { return null; }
		try {
			return ( new DateTimeImmutable( $value ) )->setTimezone( new DateTimeZone( 'UTC' ) )->getTimestamp();
		} catch ( Throwable ) {
			return null;
		}
	}
}

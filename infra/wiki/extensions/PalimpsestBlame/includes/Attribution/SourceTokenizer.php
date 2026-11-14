<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

final class SourceTokenizer {
	/** @return list<array{text:string,start:int,end:int,utf16_start:int,utf16_end:int}> */
	public static function tokenize( string $text ): array {
		$result = preg_match_all( '/\s+|[\p{L}\p{N}\p{M}_]+|[^\s\p{L}\p{N}\p{M}_]/u', $text, $matches, PREG_OFFSET_CAPTURE );
		if ( $result === false ) {
			throw new \DomainException( 'Source text is not valid UTF-8.' );
		}
		$tokens = [];
		$utf16Offset = 0;
		foreach ( $matches[0] as [ $value, $start ] ) {
			$end = $start + strlen( $value );
			$length = self::utf16Length( $value );
			$tokens[] = [
				'text' => $value,
				'start' => $start,
				'end' => $end,
				'utf16_start' => $utf16Offset,
				'utf16_end' => $utf16Offset + $length,
			];
			$utf16Offset += $length;
		}
		return $tokens;
	}

	public static function utf16Length( string $text ): int {
		$encoded = iconv( 'UTF-8', 'UTF-16LE', $text );
		return $encoded === false ? 0 : intdiv( strlen( $encoded ), 2 );
	}
}

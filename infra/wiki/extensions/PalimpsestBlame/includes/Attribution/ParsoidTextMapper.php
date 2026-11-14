<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

/** Maps only visible text whose exact source slice is proven by Parsoid DSR boundaries. */
final class ParsoidTextMapper {
	public function map( string $html, string $source, array $ids, array $tokens ): array {
		$dom = new \DOMDocument( '1.0', 'UTF-8' );
		$previous = libxml_use_internal_errors( true );
		$loaded = $dom->loadHTML( '<?xml encoding="UTF-8"><div id="pb-root">' . $html . '</div>', LIBXML_NONET | LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD );
		libxml_clear_errors();
		libxml_use_internal_errors( $previous );
		if ( !$loaded ) { return [ 'html' => $html, 'mapped_characters' => 0, 'unmapped_reasons' => [ 'parsoid-html-parse-failed' ] ]; }
		$maps = [];
		$reasons = [];
		$xpath = new \DOMXPath( $dom );
		foreach ( $xpath->query( '//*[@id="pb-root"]//p' ) as $paragraph ) {
			$generatedAncestor = false;
			for ( $ancestor = $paragraph; $ancestor instanceof \DOMElement; $ancestor = $ancestor->parentNode ) {
				if ( $this->isGenerated( $ancestor ) ) { $generatedAncestor = true; break; }
			}
			if ( $generatedAncestor ) { $reasons['generated-or-transcluded-content'] = true; continue; }
			$dsr = $this->dsrFor( $paragraph, $ids );
			if ( !$dsr ) { $reasons['paragraph-dsr-unavailable'] = true; continue; }
			$this->walk( $paragraph, $dsr[0], $dsr[1], $source, $ids, $maps, $reasons );
		}
		$mappedCharacters = 0;
		foreach ( $maps as [ $node, $byteStart, $byteEnd ] ) {
			if ( !$node->parentNode || $byteEnd - $byteStart !== strlen( $node->data ) ) { $reasons['mapped-text-length-mismatch'] = true; continue; }
			$fragment = $dom->createDocumentFragment();
			$cursor = $byteStart;
			foreach ( $tokens as $token ) {
				$from = max( $byteStart, $token['start'] );
				$to = min( $byteEnd, $token['end'] );
				if ( $from >= $to ) { continue; }
				if ( $from > $cursor ) { $fragment->appendChild( $dom->createTextNode( substr( $source, $cursor, $from - $cursor ) ) ); }
				$segment = substr( $source, $from, $to - $from );
				if ( substr( $node->data, $from - $byteStart, $to - $from ) !== $segment ) {
					$reasons['visible-text-differs-from-source'] = true;
					continue;
				}
				$span = $dom->createElement( 'span' );
				$span->setAttribute( 'data-pb-start', (string)( $token['utf16_start'] + SourceTokenizer::utf16Length( substr( $token['text'], 0, $from - $token['start'] ) ) ) );
				$span->setAttribute( 'data-pb-end', (string)( $token['utf16_start'] + SourceTokenizer::utf16Length( substr( $token['text'], 0, $to - $token['start'] ) ) ) );
				$span->setAttribute( 'data-pb-revision', (string)$token['revision_id'] );
				$span->setAttribute( 'data-pb-token', (string)$token['token_id'] );
				if ( $token['ambiguous'] ) { $span->setAttribute( 'data-pb-ambiguous', '1' ); }
				$span->appendChild( $dom->createTextNode( $segment ) );
				$fragment->appendChild( $span );
				$cursor = $to;
			}
			if ( $cursor < $byteEnd ) { $fragment->appendChild( $dom->createTextNode( substr( $source, $cursor, $byteEnd - $cursor ) ) ); }
			$node->parentNode->replaceChild( $fragment, $node );
			$mappedCharacters += SourceTokenizer::utf16Length( substr( $source, $byteStart, $byteEnd - $byteStart ) );
		}
		$root = $dom->getElementById( 'pb-root' );
		$serialized = '';
		if ( $root ) { foreach ( $root->childNodes as $child ) { $serialized .= $dom->saveHTML( $child ); } }
		return [ 'html' => $serialized, 'mapped_characters' => $mappedCharacters, 'unmapped_reasons' => array_keys( $reasons ) ];
	}

	private function walk( \DOMElement $element, int $parentStart, int $parentEnd, string $source, array $ids, array &$maps, array &$reasons ): void {
		if ( $this->isGenerated( $element ) ) { $reasons['generated-or-transcluded-content'] = true; return; }
		$dsr = $this->dsrFor( $element, $ids );
		if ( !$dsr ) { $reasons['nested-dsr-unavailable'] = true; return; }
		[ $start, $end, $openWidth, $closeWidth ] = $dsr;
		if ( $start < 0 || $end > strlen( $source ) || $start < $parentStart || $end > $parentEnd || $end < $start || $openWidth < 0 || $closeWidth < 0 || $start + $openWidth > $end - $closeWidth ) {
			$reasons['nested-dsr-out-of-parent-bounds'] = true;
			return;
		}
		$cursor = $start + $openWidth;
		$contentEnd = $end - $closeWidth;
		foreach ( iterator_to_array( $element->childNodes ) as $child ) {
			if ( $child instanceof \DOMText ) {
				$text = $child->data;
				$length = strlen( $text );
				if ( $cursor + $length <= $contentEnd && substr( $source, $cursor, $length ) === $text ) {
					$maps[] = [ $child, $cursor, $cursor + $length ];
					$cursor += $length;
				} elseif ( $text !== '' ) {
					$reasons['text-node-not-exact-at-dsr-offset'] = true;
				}
			} elseif ( $child instanceof \DOMElement ) {
				$childDsr = $this->dsrFor( $child, $ids );
				if ( !$childDsr ) { $reasons['nested-dsr-unavailable'] = true; continue; }
				if ( $childDsr[0] < $cursor || $childDsr[1] > $contentEnd ) { $reasons['child-dsr-not-contiguous'] = true; continue; }
				if ( $childDsr[0] > $cursor ) { $reasons['source-gap-unmapped'] = true; }
				$this->walk( $child, $childDsr[0], $childDsr[1], $source, $ids, $maps, $reasons );
				$cursor = $childDsr[1];
			}
		}
		if ( $cursor !== $contentEnd ) { $reasons['element-content-not-fully-mapped'] = true; }
	}

	private function dsrFor( \DOMElement $element, array $ids ): ?array {
		$id = $element->getAttribute( 'id' );
		$dsr = $id !== '' ? ( $ids[$id]['dsr'] ?? null ) : null;
		if ( !is_array( $dsr ) || count( $dsr ) < 2 || !is_int( $dsr[0] ) || !is_int( $dsr[1] ) ) { return null; }
		$open = $dsr[2] ?? 0; $close = $dsr[3] ?? 0;
		if ( !is_int( $open ) || !is_int( $close ) ) { return null; }
		return [ $dsr[0], $dsr[1], $open, $close ];
	}

	private function isGenerated( \DOMElement $element ): bool {
		$about = $element->getAttribute( 'about' );
		$typeof = $element->getAttribute( 'typeof' );
		return str_starts_with( $about, '#mwt' ) || preg_match( '/(?:^|\s)mw:(?:Transclusion|Extension|Param)(?:\/|\s|$)/', $typeof ) === 1;
	}
}

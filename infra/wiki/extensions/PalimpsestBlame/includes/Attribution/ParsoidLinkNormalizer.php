<?php
declare( strict_types = 1 );

namespace MediaWiki\Extension\PalimpsestBlame\Attribution;

use DOMDocument;
use DOMElement;

/** Rewrites Parsoid's ./Title links so they keep working outside its base href. */
final class ParsoidLinkNormalizer {
	/** @param callable(string):?string $localUrlForTitle */
	public function normalize( string $html, callable $localUrlForTitle ): string {
		$dom = new DOMDocument( '1.0', 'UTF-8' );
		$previous = libxml_use_internal_errors( true );
		try {
			$dom->loadHTML( '<?xml encoding="UTF-8"><div id="pb-link-root">' . $html . '</div>', LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD );
		} finally {
			libxml_clear_errors();
			libxml_use_internal_errors( $previous );
		}
		$root = $dom->getElementById( 'pb-link-root' );
		if ( !$root ) { return $html; }
		$links = $root->getElementsByTagName( 'a' );
		foreach ( $links as $link ) {
			if ( !$link instanceof DOMElement || !$link->hasAttribute( 'href' ) ) { continue; }
			$href = $link->getAttribute( 'href' );
			$parts = parse_url( $href );
			$path = is_array( $parts ) ? ( $parts['path'] ?? '' ) : '';
			if ( !str_starts_with( $path, './' ) ) { continue; }
			$titleText = rawurldecode( substr( $path, 2 ) );
			if ( $titleText === '' ) { continue; }
			$localUrl = $localUrlForTitle( str_replace( '_', ' ', $titleText ) );
			if ( $localUrl === null ) { continue; }
			$query = isset( $parts['query'] ) ? '?' . $parts['query'] : '';
			$fragment = isset( $parts['fragment'] ) ? '#' . $parts['fragment'] : '';
			$link->setAttribute( 'href', $localUrl . $query . $fragment );
		}
		$output = '';
		foreach ( $root->childNodes as $child ) { $output .= $dom->saveHTML( $child ); }
		return $output;
	}
}

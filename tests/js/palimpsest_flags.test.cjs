'use strict';

const test = require( 'node:test' );
const assert = require( 'node:assert/strict' );
const stacking = require( '../../infra/wiki/extensions/PalimpsestFlags/resources/stacking.js' );
const anchoring = require( '../../infra/wiki/extensions/PalimpsestFlags/resources/anchoring.js' );

test( 'strips surrounding quote marks from judge anchors', () => {
	assert.equal( anchoring.stripQuoteMarks( ' “quoted value” ' ), 'quoted value' );
	assert.equal( anchoring.stripQuoteMarks( "«quoted value»" ), 'quoted value' );
} );

test( 'stacks collisions with an eight-pixel gap and pins the active card', () => {
	const result = stacking.computePositions( [
		{ id: 'a', idealY: 10, left: 0, height: 40, tier: 'review' },
		{ id: 'b', idealY: 10, left: 1, height: 40, tier: 'admin' },
		{ id: 'c', idealY: 10, left: 2, height: 40, tier: 'review' }
	], 'c' );
	const c = result.items.find( item => item.id === 'c' );
	assert.equal( c.y, 10 );
	for ( let i = 1; i < result.items.length; i++ ) {
		assert.ok( result.items[ i ].y >= result.items[ i - 1 ].y + result.items[ i - 1 ].height + 8 );
	}
} );

test( 'default placement orders by anchor, left edge, tier, then id', () => {
	const result = stacking.computePositions( [
		{ id: 'z', idealY: 3, left: 4, height: 1, tier: 'review' },
		{ id: 'a', idealY: 3, left: 4, height: 1, tier: 'admin' },
		{ id: 'b', idealY: 3, left: 2, height: 1, tier: 'review' }
	] );
	assert.deepEqual( result.items.map( item => item.id ), [ 'b', 'a', 'z' ] );
} );

test( 'filter selection starts at the first visible flag', () => {
	const rows = [ { flag: { id: 'fact', kind: 'FACT' } }, { flag: { id: 'wording', kind: 'FRAMING' } }, { flag: { id: 'wording-2', kind: 'FRAMING' } } ];
	assert.equal( stacking.firstVisibleId( rows, 'FRAMING' ), 'wording' );
	assert.equal( stacking.firstVisibleId( rows, 'MOTIVE' ), null );
} );

test( 'steppers are disabled when filtering leaves one actionable flag', () => {
	const rows = [ { flag: { id: 'a', kind: 'FACT' } }, { flag: { id: 'b', kind: 'FRAMING' } } ];
	assert.equal( stacking.stepperDisabled( rows, new Set(), 'FACT' ), true );
	assert.equal( stacking.stepperDisabled( rows, new Set(), null ), false );
	assert.equal( stacking.stepperDisabled( rows, new Set( [ 'a' ] ), null ), true );
} );

test( 'approved palette combinations meet 4.5:1 contrast', () => {
	const pairs = [ [ '#b32424', '#ffffff' ], [ '#6b4ba1', '#ffffff' ], [ '#f0b400', '#101418' ], [ '#b95000', '#ffffff' ], [ '#101418', '#ffffff' ], [ '#3366cc', '#ffffff' ], [ '#0e7369', '#ffffff' ], [ '#fd7865', '#101418' ], [ '#bba2e5', '#101418' ], [ '#eeb533', '#101418' ], [ '#ff9e5e', '#101418' ], [ '#080a0c', '#f8f9fa' ], [ '#88a3e8', '#101418' ], [ '#59d1c5', '#101418' ] ];
	const luminance = hex => { const rgb = hex.match( /\w\w/g ).map( h => parseInt( h, 16 ) / 255 ).map( c => c <= .04045 ? c / 12.92 : ( ( c + .055 ) / 1.055 ) ** 2.4 ); return .2126 * rgb[ 0 ] + .7152 * rgb[ 1 ] + .0722 * rgb[ 2 ]; };
	pairs.forEach( ( [ background, foreground ] ) => { const a = luminance( background ), b = luminance( foreground ); assert.ok( ( Math.max( a, b ) + .05 ) / ( Math.min( a, b ) + .05 ) >= 4.5, background + '/' + foreground ); } );
} );

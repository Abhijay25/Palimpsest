import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogVectorQuery } from '../server/search-query.mjs';

const edition = (language, page, revision) => ({ language, sourcePageId: page, sourceAnchorRevision: revision });
const catalog = [
  { id: 'Q1', articles: { en: edition('en', 10, 100), fi: edition('fi', 20, 200) } },
  { id: 'Q2', articles: { sv: edition('sv', 30, 300) } },
];

test('catalog topic and exact source identities restrict candidates before top-k', () => {
  const { sql, params } = catalogVectorQuery(catalog, [.1, .2]);
  assert.match(sql, /WHERE topic_id IN \(\?,\?\) AND \(topic_id,language,source_page_id,source_revision_id\) IN/);
  assert.ok(sql.indexOf('WHERE') < sql.indexOf('LIMIT 9'));
  assert.deepEqual(params, ['[0.1,0.2]', 'Q1', 'Q2', 'Q1', 'en', 10, 100, 'Q1', 'fi', 20, 200, 'Q2', 'sv', 30, 300]);
  assert.equal((sql.match(/\?/g) || []).length, params.length);
  assert.ok(!params.includes(999)); // Same-topic unknown source page cannot qualify.
});

test('empty catalog fails closed instead of searching the shared corpus', () => {
  const { sql, params } = catalogVectorQuery([], [1]);
  assert.match(sql, /WHERE 1=0 ORDER BY/);
  assert.deepEqual(params, ['[1]']);
});

test('mixed catalog excludes unknown, mismatched and invalid source identities', () => {
  const mixed = [
    ...catalog,
    { id: 'Q3', articles: { en: edition('en', 999, undefined) } },
    { id: 'Q4', articles: { en: edition('fi', 888, 8888) } },
    { id: 'Q5', articles: { de: edition('de', 777, 7777) } },
    { id: 'Q6 OR 1=1', articles: { en: edition('en', 666, 6666) } },
  ];
  assert.deepEqual(catalogVectorQuery(mixed, [1]), catalogVectorQuery(catalog, [1]));
});

test('related search excludes selected topic with a bound parameter', () => {
  const { sql, params } = catalogVectorQuery(catalog, [1], 'Q1');
  assert.match(sql, /AND topic_id<>\? ORDER BY/);
  assert.equal(params.at(-1), 'Q1');
  assert.equal((sql.match(/\?/g) || []).length, params.length);
  assert.ok(!sql.includes('Q1'));
});

test('repeated catalog entries do not multiply bindings', () => {
  assert.deepEqual(catalogVectorQuery([...catalog, ...catalog], [1]), catalogVectorQuery(catalog, [1]));
});


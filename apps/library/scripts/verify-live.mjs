import assert from 'node:assert/strict';
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { DATA } from '../server/catalog.mjs';

const origin = process.env.LIBRARY_URL || 'http://127.0.0.1:5180';
const observations = [];
async function request(route, options) {
  const response = await fetch(origin + route, options);
  const data = await response.json();
  return { response, data };
}
const { data: catalog, response } = await request('/api/catalog');
assert.equal(response.status, 200);
assert.equal(catalog.topicCount, 3);
assert.equal(catalog.articleCount, 9);
for (const topic of catalog.topics) {
  assert.deepEqual(Object.keys(topic.articles).sort(), ['en', 'fi', 'sv']);
  for (const lang of ['en', 'fi', 'sv']) {
    const article = topic.articles[lang];
    const { data: history, response: historyResponse } = await request(
      '/api/topics/' + topic.id + '/revisions?lang=' + lang,
    );
    assert.equal(historyResponse.status, 200, JSON.stringify(history));
    assert.equal(history.versions.length, article.revisionCount);
    assert.equal(
      new Set(history.versions.map((r) => r.revision_id)).size,
      article.revisionCount,
    );
    assert.equal(history.versions[0].revision_id, article.anchorRevision);
    history.versions.forEach((row, i) => {
      assert.ok(row.source?.revision_id > 0);
      assert.ok(row.url.startsWith('http://127.0.0.1:'));
      if (i) assert.ok(history.versions[i - 1].timestamp >= row.timestamp);
    });
    const params = new URLSearchParams({
      action: 'palimpsestblame',
      op: 'analyze',
      title: article.title,
      revision: String(article.anchorRevision),
    });
    const started = performance.now();
    const { data: analysis, response: analysisResponse } = await request(
      '/api/wiki/' + lang + '?' + params,
    );
    assert.equal(analysisResponse.status, 200);
    const ready = analysis.palimpsestblame;
    assert.equal(ready.status, 'ready', JSON.stringify(ready));
    assert.equal(ready.snapshot.revision_id, article.anchorRevision);
    assert.equal(ready.page.id, article.pageId);
    assert.equal(ready.coverage.provenance_status, 'verified');
    assert.equal(ready.coverage.history_complete, true);
    assert.ok(ready.html.includes('data-pb-start'));
    assert.ok(ready.mapping.mapped_characters > 0);
    observations.push({
      topic: topic.id,
      lang,
      revisions: history.versions.length,
      analysisMs: Math.round(performance.now() - started),
      mappedCharacters: ready.mapping.mapped_characters,
      unmapped: ready.mapping.unmapped_reasons,
    });
  }
}
const queries = [
  { query: 'Vyborg tower built between 1547 and 1550', expected: ['Q4241896'] },
  {
    query: 'Bronze Age burial mounds in Siuntio',
    expected: ['Q110908561', 'Q110908692'],
  },
  {
    query: 'pronssikautinen hautapaikka Siuntiossa',
    expected: ['Q110908561', 'Q110908692'],
  },
];
const searches = [];
for (const row of queries) {
  const { data, response } = await request('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: row.query }),
  });
  assert.equal(response.status, 200, JSON.stringify(data));
  assert.equal(data.dimensions, 1024);
  assert.ok(data.source.includes('MariaDB'));
  assert.ok(
    row.expected.includes(data.results[0]?.id),
    JSON.stringify({ query: row.query, data }),
  );
  assert.equal(
    new Set(data.results.map((r) => r.id)).size,
    data.results.length,
  );
  searches.push(data);
}
const first = catalog.topics[0];
const negatives = [
  ['/api/topics/Q0/revisions?lang=en', 404],
  ['/api/topics/' + first.id + '/revisions?lang=de', 400],
  ['/reader/' + first.id + '/en/999999999', 404],
  ['/api/wiki/en?action=query&list=allusers', 403],
  [
    '/api/wiki/en?' +
      new URLSearchParams({
        action: 'palimpsestblame',
        title: first.articles.en.title,
        revision: '999999999',
      }),
    404,
  ],
];
for (const [route, status] of negatives) {
  const { response, data } = await request(route);
  assert.equal(response.status, status, JSON.stringify(data));
  assert.ok(data.error);
  assert.equal(data.palimpsestblame, undefined);
}
const result = {
  origin,
  catalog: {
    topics: catalog.topicCount,
    articles: catalog.articleCount,
    revisions: observations.reduce((sum, row) => sum + row.revisions, 0),
  },
  observations,
  searches,
  negativeGuards: negatives.length,
  passed: true,
};
await mkdir(path.join(DATA, 'evidence'), { recursive: true });
await writeFile(
  path.join(DATA, 'evidence/native.json'),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  canonical,
  verifyBundle,
  orderRevisions,
  editionSlot,
  topicLayout,
  groupHits,
} from '../server/domain.mjs';

test('provenance ordinary control passes; corruption and cross-language identity fail for their intended reasons', () => {
  const payload = { pages: [{ title: 'Åbo', source_page_id: 1 }] };
  const bundle = {
    schema_version: 1,
    language: 'fi',
    source_wiki: 'fiwiki',
    payload,
    sha256: createHash('sha256').update(canonical(payload)).digest('hex'),
  };
  assert.deepEqual(verifyBundle(bundle, 'fi'), payload.pages);
  assert.throws(
    () => verifyBundle({ ...bundle, sha256: '0'.repeat(64) }, 'fi'),
    /checksum mismatch/,
  );
  assert.throws(() => verifyBundle(bundle, 'sv'), /identity/);
});
test('equal-second chronology has a deterministic tie rule and rejects duplicate local IDs', () => {
  const rows = [
    { local_revision_id: 4, timestamp: '2020-02-01T00:00:00Z' },
    { local_revision_id: 9, timestamp: '2020-02-01T00:00:00Z' },
    { local_revision_id: 2, timestamp: '2010-01-01T00:00:00Z' },
  ];
  assert.deepEqual(
    orderRevisions(rows).map((r) => r.local_revision_id),
    [9, 4, 2],
  );
  assert.deepEqual(
    rows.map((r) => r.local_revision_id),
    [4, 9, 2],
  );
  assert.throws(() => orderRevisions([...rows, rows[0]]), /duplicate/);
});
test('hundreds of editions alternate uniquely in a forward new-to-old corridor', () => {
  const slots = Array.from({ length: 705 }, (_, i) => editionSlot(i));
  assert.equal(slots[0].side, 'left');
  assert.equal(slots[1].side, 'right');
  assert.equal(new Set(slots.map((row) => row.side + ':' + row.z)).size, 705);
  slots.forEach((row, i) => {
    if (i > 1) assert.ok(row.z <= slots[i - 1].z);
  });
  assert.throws(() => editionSlot(-1), /index/);
});
test('layout preserves a related pair without using article labels to assign positions', () => {
  const topic = (id, embedding) => ({
    id,
    articles: Object.fromEntries(
      ['en', 'fi', 'sv'].map((lang) => [lang, { embedding }]),
    ),
  });
  const input = [
    topic('A', [1, 0, 0]),
    topic('B', [0.99, 0.1, 0]),
    topic('C', [0, 0, 1]),
  ];
  const first = topicLayout(input),
    second = topicLayout(input);
  assert.deepEqual(first, second);
  const distance = (a, b) =>
    Math.hypot(a.position[0] - b.position[0], a.position[2] - b.position[2]);
  assert.ok(distance(first[0], first[1]) < distance(first[0], first[2]));
  assert.ok(first.every((row) => row.position.every(Number.isFinite)));
});
test('multilingual vector hits group by verified topic identity while retaining matched language', () => {
  assert.deepEqual(
    groupHits([
      { topic_id: 'Q1', language: 'sv', title: 'Torn', distance: 0.1 },
      { topic_id: 'Q1', language: 'en', title: 'Tower', distance: 0.2 },
      { topic_id: 'Q2', language: 'fi', title: 'Mäki', distance: 0.3 },
    ]),
    [
      { id: 'Q1', distance: 0.1, matchedLanguage: 'sv', matchedTitle: 'Torn' },
      { id: 'Q2', distance: 0.3, matchedLanguage: 'fi', matchedTitle: 'Mäki' },
    ],
  );
});

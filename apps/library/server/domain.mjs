import { createHash } from 'node:crypto';

export const LANGUAGES = ['en', 'fi', 'sv'];
export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object')
    return (
      '{' +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ':' + canonical(value[key]))
        .join(',') +
      '}'
    );
  return JSON.stringify(value);
}
export function verifyBundle(bundle, lang) {
  if (
    bundle?.schema_version !== 1 ||
    bundle.language !== lang ||
    bundle.source_wiki !== lang + 'wiki'
  )
    throw new Error('Unsupported provenance identity');
  if (
    createHash('sha256').update(canonical(bundle.payload)).digest('hex') !==
    bundle.sha256
  )
    throw new Error('Provenance checksum mismatch');
  return bundle.payload.pages;
}
export function orderRevisions(revisions) {
  const ids = new Set();
  for (const revision of revisions) {
    if (
      !Number.isSafeInteger(revision.local_revision_id) ||
      revision.local_revision_id <= 0 ||
      ids.has(revision.local_revision_id) ||
      !Number.isFinite(Date.parse(revision.timestamp))
    )
      throw new Error('Invalid or duplicate revision identity');
    ids.add(revision.local_revision_id);
  }
  return [...revisions].sort(
    (a, b) =>
      b.timestamp.localeCompare(a.timestamp) ||
      b.local_revision_id - a.local_revision_id,
  );
}
export function editionSlot(index) {
  if (!Number.isSafeInteger(index) || index < 0)
    throw new Error('Invalid edition index');
  return {
    side: index % 2 === 0 ? 'left' : 'right',
    row: Math.floor(index / 2),
    z: -Math.floor(index / 2) * 5 - 5,
  };
}
export function cosine(a, b) {
  const dot = a.reduce((sum, value, i) => sum + value * b[i], 0);
  return (
    dot /
    (Math.sqrt(a.reduce((sum, value) => sum + value * value, 0)) *
      Math.sqrt(b.reduce((sum, value) => sum + value * value, 0)))
  );
}
export function topicLayout(topics) {
  if (topics.length !== 3)
    throw new Error(
      'This deterministic three-point layout expects the frozen three-topic corpus',
    );
  const vectors = topics.map((topic) => {
    const rows = LANGUAGES.map((lang) => topic.articles[lang].embedding);
    return rows[0].map(
      (_, i) => rows.reduce((sum, row) => sum + row[i], 0) / rows.length,
    );
  });
  const d = (i, j) =>
    Math.sqrt(Math.max(0, 2 * (1 - cosine(vectors[i], vectors[j]))));
  const ab = Math.max(d(0, 1), 1e-6),
    ac = d(0, 2),
    bc = d(1, 2);
  const x = (ac * ac + ab * ab - bc * bc) / (2 * ab),
    z = Math.sqrt(Math.max(0, ac * ac - x * x));
  const points = [
    [0, 0],
    [ab, 0],
    [x, z],
  ];
  const center = points.reduce(
    (s, p) => [s[0] + p[0] / 3, s[1] + p[1] / 3],
    [0, 0],
  );
  const scale = 24 / Math.max(ab, ac, bc, 1e-6);
  return topics.map((topic, i) => ({
    id: topic.id,
    position: [
      (points[i][0] - center[0]) * scale,
      0,
      (points[i][1] - center[1]) * scale,
    ],
    distances: topics.map((other, j) => ({
      id: other.id,
      distance: 1 - cosine(vectors[i], vectors[j]),
    })),
  }));
}
export function groupHits(rows) {
  const grouped = new Map();
  for (const row of rows) {
    if (!grouped.has(row.topic_id))
      grouped.set(row.topic_id, {
        id: row.topic_id,
        distance: Number(row.distance),
        matchedLanguage: row.language,
        matchedTitle: row.title,
      });
  }
  return [...grouped.values()];
}
export function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        c
      ],
  );
}

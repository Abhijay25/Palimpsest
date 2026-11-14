import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  LANGUAGES,
  verifyBundle,
  orderRevisions,
  topicLayout,
} from './domain.mjs';

export const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../..',
);
export const DATA =
  process.env.LIBRARY_DATA_ROOT || path.join(ROOT, '.local/library');
export const loadConfig = async () =>
  JSON.parse(await readFile(path.join(DATA, 'config.json'), 'utf8'));
export async function loadCatalog() {
  const raw = JSON.parse(
    await readFile(path.join(DATA, 'catalog.json'), 'utf8'),
  );
  const bundles = Object.fromEntries(
    await Promise.all(
      LANGUAGES.map(async (lang) => [
        lang,
        verifyBundle(
          JSON.parse(
            await readFile(
              path.join(DATA, 'wiki/blame-provenance', lang + '.json'),
              'utf8',
            ),
          ),
          lang,
        ),
      ]),
    ),
  );
  const layout = topicLayout(raw.topics);
  return raw.topics.map((topic) => {
    const articles = {};
    for (const lang of LANGUAGES) {
      const source = topic.articles[lang];
      if (!source || source.lang !== lang || source.wikidata_id !== topic.id)
        throw new Error('Incomplete or mismatched trilingual topic');
      const page = bundles[lang].find(
        (row) => row.source_page_id === source.page_id,
      );
      if (
        !page?.history_complete ||
        page.title !== source.title ||
        page.source_anchor_revision_id !== source.rev_id
      )
        throw new Error(`Verified history missing for ${lang}:${source.title}`);
      const revisions = orderRevisions(page.revisions);
      const anchor = revisions.find(
        (row) => row.source_revision_id === page.source_anchor_revision_id,
      );
      if (!anchor || !revisions.length)
        throw new Error('Imported source anchor missing');
      articles[lang] = {
        language: lang,
        title: source.title,
        pageId: page.local_page_id,
        sourcePageId: source.page_id,
        anchorRevision: anchor.local_revision_id,
        sourceAnchorRevision: source.rev_id,
        anchorTimestamp: anchor.timestamp,
        earliestTimestamp: revisions.at(-1).timestamp,
        revisionCount: revisions.length,
        sourceUrl: source.url,
        embedding: source.embedding,
        embeddingTruncated: source.embedding_truncated,
        revisions,
      };
    }
    return {
      id: topic.id,
      title: topic.title,
      summary: topic.summary,
      articles,
      ...layout.find((row) => row.id === topic.id),
    };
  });
}
export function publicTopic(topic) {
  return {
    ...topic,
    articles: Object.fromEntries(
      LANGUAGES.map((lang) => {
        const { embedding, revisions, ...article } = topic.articles[lang];
        return [lang, article];
      }),
    ),
  };
}

import mysql from 'mysql2/promise';
import { loadCatalog, loadConfig } from '../server/catalog.mjs';

const config = await loadConfig();
const topics = await loadCatalog();
const db = await mysql.createConnection(config.database);
try {
  await db.query(`CREATE TABLE IF NOT EXISTS library_articles (
    topic_id VARCHAR(32) NOT NULL,
    language CHAR(2) NOT NULL,
    source_page_id BIGINT UNSIGNED NOT NULL,
    source_revision_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(255) NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    PRIMARY KEY (language,source_page_id),
    VECTOR INDEX library_semantic (embedding) M=6 DISTANCE=cosine
  )`);
  await db.beginTransaction();
  for (const topic of topics)
    for (const article of Object.values(topic.articles)) {
      if (
        article.embedding.length !== 1024 ||
        !article.embedding.every(Number.isFinite)
      )
        throw new Error('Invalid embedding dimensions/values');
      await db.execute(
        `INSERT INTO library_articles (topic_id,language,source_page_id,source_revision_id,title,embedding)
      VALUES (?,?,?,?,?,VEC_FromText(?)) ON DUPLICATE KEY UPDATE source_revision_id=VALUES(source_revision_id),title=VALUES(title),embedding=VALUES(embedding)`,
        [
          topic.id,
          article.language,
          article.sourcePageId,
          article.sourceAnchorRevision,
          article.title,
          JSON.stringify(article.embedding),
        ],
      );
    }
  await db.commit();
  const [rows] = await db.query(
    'SELECT VERSION() AS version,COUNT(*) AS articles FROM library_articles',
  );
  console.log(
    JSON.stringify(
      {
        database: rows[0],
        topics: topics.map((t) => ({
          id: t.id,
          languages: Object.keys(t.articles),
          revisions: Object.fromEntries(
            Object.entries(t.articles).map(([lang, a]) => [
              lang,
              a.revisionCount,
            ]),
          ),
        })),
      },
      null,
      2,
    ),
  );
} finally {
  await db.end();
}

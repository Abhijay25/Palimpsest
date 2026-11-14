// The shared index contains many more articles than this verified Library.
// Restrict candidates before top-k so unavailable books never displace real ones.
export function catalogVectorQuery(topics, embedding, excludeTopic = null) {
  const editions = new Map();
  for (const topic of topics) {
    if (!/^Q[1-9]\d*$/.test(topic?.id || '')) continue;
    for (const [language, article] of Object.entries(topic.articles || {})) {
      if (
        !['en', 'fi', 'sv'].includes(language) ||
        article?.language !== language ||
        !Number.isSafeInteger(article.sourcePageId) || article.sourcePageId <= 0 ||
        !Number.isSafeInteger(article.sourceAnchorRevision) || article.sourceAnchorRevision <= 0
      ) continue;
      const tuple = [topic.id, language, article.sourcePageId, article.sourceAnchorRevision];
      editions.set(JSON.stringify(tuple), tuple);
    }
  }
  const rows = [...editions.values()];
  const topicIds = [...new Set(rows.map((row) => row[0]))];
  const params = [JSON.stringify(embedding)];
  let where = '1=0';
  if (rows.length) {
    where = `topic_id IN (${topicIds.map(() => '?').join(',')}) AND ` +
      `(topic_id,language,source_page_id,source_revision_id) IN (${rows.map(() => '(?,?,?,?)').join(',')})`;
    params.push(...topicIds, ...rows.flat());
    if (excludeTopic !== null) {
      where += ' AND topic_id<>?';
      params.push(excludeTopic);
    }
  }
  return {
    sql: 'SELECT topic_id,language,title,VEC_DISTANCE_COSINE(embedding,VEC_FromText(?)) AS distance ' +
      `FROM library_articles WHERE ${where} ORDER BY distance,topic_id,language,source_page_id LIMIT 9`,
    params,
  };
}

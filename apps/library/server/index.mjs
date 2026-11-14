import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import mysql from 'mysql2/promise';
import { ROOT, loadConfig, loadCatalog, publicTopic } from './catalog.mjs';
import { LANGUAGES, groupHits, escapeHtml } from './domain.mjs';
import { catalogVectorQuery } from './search-query.mjs';

const APP = path.join(ROOT, 'apps/library');
const config = await loadConfig();
const port = Number(process.env.PORT || 5180);
const db = mysql.createPool({
  ...config.database,
  connectionLimit: 3,
  waitForConnections: true,
  queueLimit: 8,
});
const nativeDir = path.join(
  ROOT,
  'infra/wiki/extensions/PalimpsestBlame/resources',
);
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.png': 'image/png',
};
const error = (message, status = 400) =>
  Object.assign(new Error(message), { status });
let embeddingRequests = 0;

function json(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(data));
}
async function body(req) {
  let text = '';
  for await (const chunk of req) {
    text += chunk;
    if (Buffer.byteLength(text) > 65536)
      throw error('Request is too large.', 413);
  }
  return text;
}
async function file(res, filename, type) {
  const content = await readFile(filename);
  res.writeHead(200, {
    'Content-Type':
      type || mime[path.extname(filename)] || 'application/octet-stream',
    'Cache-Control': 'no-cache',
  });
  res.end(content);
}
function getArticle(topics, id, lang) {
  if (!LANGUAGES.includes(lang))
    throw error('Choose English, Finnish or Swedish.');
  const topic = topics.find((row) => row.id === id);
  if (!topic) throw error('This topic is outside the curated collection.', 404);
  return { topic, article: topic.articles[lang] };
}
function admittedRevision(article, value) {
  const id = Number(value);
  if (
    !Number.isSafeInteger(id) ||
    !article.revisions.some((row) => row.local_revision_id === id)
  )
    throw error('This edition is outside the verified imported history.', 404);
  return id;
}
function absoluteLinks(value, base) {
  if (Array.isArray(value)) return value.map((row) => absoluteLinks(row, base));
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        typeof child === 'string' && /(^url$|_url$)/.test(key)
          ? new URL(child, base).href
          : absoluteLinks(child, base),
      ]),
    );
  return value;
}
async function wikiFetch(lang, params, req, res, method = 'GET') {
  const headers = { Accept: 'application/json' };
  if (req.headers.cookie) headers.Cookie = req.headers.cookie;
  const options = {
    method,
    headers,
    signal: AbortSignal.timeout(30000),
    redirect: 'error',
  };
  let url = config.wikis[lang] + '/api.php';
  if (method === 'POST') {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    options.body = params.toString();
  } else url += '?' + params;
  const response = await fetch(url, options);
  const cookies = response.headers.getSetCookie?.();
  if (cookies?.length) res.setHeader('Set-Cookie', cookies);
  if (!response.ok)
    throw error('The article service is unavailable. Please retry.', 502);
  return response.json();
}
async function revisions(topics, id, lang, req, res) {
  const { topic, article } = getArticle(topics, id, lang);
  const allowed = new Map(
    article.revisions.map((row) => [row.local_revision_id, row]),
  );
  const found = [];
  let cursor = null;
  const seen = new Set();
  for (let page = 0; page < 100; page++) {
    const params = new URLSearchParams({
      action: 'palimpsestblame',
      format: 'json',
      formatversion: '2',
      op: 'versions',
      title: article.title,
      mode: 'range',
      from: article.earliestTimestamp,
      to: article.anchorTimestamp,
      limit: '100',
    });
    if (cursor) params.set('cursor', cursor);
    const data = await wikiFetch(lang, params, req, res);
    const result = data.palimpsestblame;
    if (
      data.error ||
      result?.status !== 'ready' ||
      result.coverage?.provenance_status !== 'verified' ||
      !result.coverage.history_complete
    )
      throw error(
        'Verified edition history is unavailable. Check article coverage and retry.',
        503,
      );
    for (const row of result.versions || []) {
      const imported = allowed.get(row.revision_id);
      if (!imported) continue;
      if (seen.has(row.revision_id))
        throw error('The history service repeated an edition.', 502);
      if (row.timestamp !== imported.timestamp)
        throw error(
          'The edition history changed. Refresh the collection.',
          503,
        );
      seen.add(row.revision_id);
      found.push({
        ...row,
        source: row.source || {
          wiki: lang + 'wiki',
          page_id: article.sourcePageId,
          revision_id: imported.source_revision_id,
          url: imported.source_url,
        },
      });
    }
    if (!result.continuation) break;
    if (result.continuation === cursor)
      throw error('The history service did not advance.', 502);
    cursor = result.continuation;
  }
  if (found.length !== allowed.size)
    throw error(
      'Some imported editions are unavailable. The corridor has not been substituted with a partial history.',
      503,
    );
  found.sort(
    (a, b) =>
      b.timestamp.localeCompare(a.timestamp) || b.revision_id - a.revision_id,
  );
  return {
    topicId: topic.id,
    language: lang,
    title: article.title,
    anchorRevision: article.anchorRevision,
    anchorTimestamp: article.anchorTimestamp,
    coverage: 'verified',
    versions: absoluteLinks(found, config.wikis[lang]),
  };
}

async function proxyWiki(req, res, url, lang, topics) {
  const params =
    req.method === 'POST'
      ? new URLSearchParams(await body(req))
      : new URLSearchParams(url.searchParams);
  params.set('format', 'json');
  params.set('formatversion', '2');
  const action = params.get('action');
  if (
    action === 'query' &&
    req.method === 'GET' &&
    params.get('meta') === 'tokens' &&
    (!params.get('type') || params.get('type') === 'csrf')
  ) {
    return json(
      res,
      200,
      await wikiFetch(
        lang,
        new URLSearchParams({
          action: 'query',
          meta: 'tokens',
          type: 'csrf',
          format: 'json',
          formatversion: '2',
        }),
        req,
        res,
      ),
    );
  }
  if (action !== 'palimpsestblame')
    throw error('Only the public article history API is available here.', 403);
  const op = params.get('op') || 'analyze';
  if (
    !['analyze', 'versions', 'build', 'status'].includes(op) ||
    (req.method === 'POST') !== (op === 'build')
  )
    throw error('Unsupported history operation.', 405);
  const title = (params.get('title') || '').replaceAll('_', ' ');
  const topic = topics.find((row) => row.articles[lang].title === title);
  if (!topic)
    throw error('This article is outside the curated collection.', 404);
  const article = topic.articles[lang];
  if (op !== 'versions')
    params.set(
      'revision',
      String(admittedRevision(article, params.get('revision'))),
    );
  const allowedParams = new Set([
    'action',
    'format',
    'formatversion',
    'op',
    'title',
    'revision',
    'ranges',
    'mode',
    'from',
    'to',
    'limit',
    'cursor',
    'jobid',
    'token',
  ]);
  for (const key of params.keys())
    if (!allowedParams.has(key)) throw error('Unsupported history parameter.');
  if ((params.get('ranges') || '').length > 16000)
    throw error('The selection is too large.', 413);
  const data = await wikiFetch(lang, params, req, res, req.method);
  const result = data.palimpsestblame;
  if (op === 'versions' && result?.status === 'ready') {
    const allowed = new Set(
      article.revisions.map((row) => row.local_revision_id),
    );
    result.versions = (result.versions || []).filter((row) =>
      allowed.has(row.revision_id),
    );
    if (
      result.selected_revision_id &&
      !allowed.has(result.selected_revision_id)
    )
      result.selected_revision_id = null;
  }
  json(res, 200, absoluteLinks(data, config.wikis[lang]));
}
function readerDocument(topic, article, revision, lang) {
  const context = {
    topicId: topic.id,
    language: lang,
    title: article.title,
    pageId: article.pageId,
    revision,
    latestImported: article.anchorRevision,
    wiki: config.wikis[lang],
    revisions: article.revisions.map((row) => row.local_revision_id),
  };
  const encoded = JSON.stringify(context).replaceAll('<', '\\u003c');
  return `<!doctype html><html lang="${lang}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(article.title)} · Palimpsest</title><link rel="stylesheet" href="/api/native/blame.css"><link rel="stylesheet" href="/api/reader.css"><script id="reader-context" type="application/json">${encoded}</script><script defer src="/api/native/helpers.js"></script><script defer src="/api/reader-adapter.js"></script></head><body><main><header class="reader-article-heading"><h1>${escapeHtml(article.title)}</h1><p>Wikipedia · ${lang.toUpperCase()} · edition ${revision}</p></header><div id="mw-content-text"><article class="mw-parser-output"></article><section id="palimpsest-blame" data-revision="${revision}" aria-label="Passage history"><p role="status">Opening this edition and preparing its wording history…</p></section></div></main></body></html>`;
}

const server = http.createServer(async (req, res) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https: http://127.0.0.1:*; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
  );
  try {
    const url = new URL(req.url, 'http://127.0.0.1:' + port);
    if (req.url.length > 65536) throw error('Request is too large.', 413);
    if (
      req.method === 'POST' &&
      req.headers.origin &&
      ![
        'http://127.0.0.1:5180',
        'http://localhost:5180',
        'http://127.0.0.1:5181',
        'http://localhost:5181',
      ].includes(req.headers.origin)
    )
      throw error('This request origin is not allowed.', 403);
    const natives = {
      '/api/native/helpers.js': 'helpers.js',
      '/api/native/controller.js': 'ext.palimpsestBlame.js',
      '/api/native/blame.css': 'ext.palimpsestBlame.css',
    };
    if (natives[url.pathname])
      return await file(res, path.join(nativeDir, natives[url.pathname]));
    if (url.pathname === '/api/reader-adapter.js')
      return await file(res, path.join(APP, 'server/reader-adapter.js'));
    if (url.pathname === '/api/reader.css')
      return await file(res, path.join(APP, 'public/reader.css'));
    if (url.pathname.startsWith('/api/fonts/')) {
      const fonts = {
        'book.woff2':
          '@fontsource/cormorant-garamond/files/cormorant-garamond-latin-400-normal.woff2',
        'book-semibold.woff2':
          '@fontsource/cormorant-garamond/files/cormorant-garamond-latin-600-normal.woff2',
        'ui.woff2': '@fontsource/inter/files/inter-latin-400-normal.woff2',
      };
      const selected = fonts[url.pathname.slice('/api/fonts/'.length)];
      if (!selected) throw error('Font not found.', 404);
      return await file(res, path.join(APP, 'node_modules', selected));
    }
    if (
      url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/reader/')
    ) {
      const topics = await loadCatalog();
      if (url.pathname === '/api/catalog' && req.method === 'GET')
        return json(res, 200, {
          schemaVersion: 1,
          topics: topics.map(publicTopic),
          topicCount: topics.length,
          articleCount: topics.length * 3,
          model: 'bge-m3',
          dimensions: 1024,
          layout:
            'multilingual-mean cosine distance, deterministic three-point projection',
        });
      let match = /^\/api\/topics\/(Q\d+)\/revisions$/.exec(url.pathname);
      if (match && req.method === 'GET')
        return json(
          res,
          200,
          await revisions(
            topics,
            match[1],
            url.searchParams.get('lang') || 'en',
            req,
            res,
          ),
        );
      match = /^\/api\/related\/(Q\d+)$/.exec(url.pathname);
      if (match && req.method === 'GET') {
        const { article } = getArticle(topics, match[1], 'en');
        const candidates = catalogVectorQuery(topics, article.embedding, match[1]);
        const [rows] = await db.execute(candidates.sql, candidates.params);
        return json(res, 200, {
          results: groupHits(rows),
          source: 'MariaDB cosine vector query',
        });
      }
      if (url.pathname === '/api/search' && req.method === 'POST') {
        const input = JSON.parse(await body(req));
        if (!input || typeof input !== 'object' || Array.isArray(input))
          throw error('Enter a search query as a JSON object.');
        const query = String(input.query || '').trim();
        if (!query || query.length > 1000)
          throw error('Enter a topic or question up to 1,000 characters.');
        if (embeddingRequests >= 2)
          throw error('Search is busy. Please try again in a moment.', 429);
        embeddingRequests++;
        try {
          const started = performance.now();
          const response = await fetch(config.ollama + '/api/embed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: config.model,
              input: query,
              truncate: false,
              options: { num_ctx: 8192, num_batch: 8192 },
            }),
            signal: AbortSignal.timeout(60000),
          });
          if (!response.ok)
            throw error(
              'The local embedding model is unavailable. Please retry after it is ready.',
              503,
            );
          const result = await response.json();
          const embedding = result.embeddings?.[0];
          if (embedding?.length !== 1024 || !embedding.every(Number.isFinite))
            throw error(
              'The embedding model returned an incompatible vector.',
              503,
            );
          const candidates = catalogVectorQuery(topics, embedding);
          const [rows] = await db.execute(candidates.sql, candidates.params);
          return json(res, 200, {
            query,
            results: groupHits(rows),
            model: config.model,
            dimensions: embedding.length,
            elapsedMs: Math.round(performance.now() - started),
            source: 'Ollama bge-m3 + MariaDB cosine vector query',
          });
        } finally {
          embeddingRequests--;
        }
      }
      match = /^\/api\/wiki\/(en|fi|sv)$/.exec(url.pathname);
      if (match && ['GET', 'POST'].includes(req.method))
        return await proxyWiki(req, res, url, match[1], topics);
      match = /^\/reader\/(Q\d+)\/(en|fi|sv)\/(\d+)$/.exec(url.pathname);
      if (match && req.method === 'GET') {
        const { topic, article } = getArticle(topics, match[1], match[2]);
        const revision = admittedRevision(article, match[3]);
        res.writeHead(200, {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        });
        return res.end(readerDocument(topic, article, revision, match[2]));
      }
      throw error('This Library route does not exist.', 404);
    }
    if (req.method !== 'GET' && req.method !== 'HEAD')
      throw error('Method not allowed.', 405);
    const dist = path.join(APP, 'dist');
    const decoded = decodeURIComponent(url.pathname);
    const candidate = path.resolve(dist, '.' + decoded);
    if (!candidate.startsWith(dist + path.sep) && candidate !== dist)
      throw error('Invalid asset path.', 403);
    try {
      if ((await stat(candidate)).isFile()) return await file(res, candidate);
    } catch {}
    return await file(res, path.join(dist, 'index.html'));
  } catch (cause) {
    if (!cause.status)
      console.error('[library]', cause.code || cause.name, cause.message);
    const status = cause.status || (cause instanceof SyntaxError ? 400 : 503);
    const message = cause.status
      ? cause.message
      : cause instanceof SyntaxError
        ? 'The request is not valid JSON.'
        : 'The Library is not ready. Check setup, then retry.';
    if (!res.headersSent) json(res, status, { error: message });
    else res.end();
  }
});
server.listen(port, '127.0.0.1', () =>
  console.log(`Palimpsest Library API listening on http://127.0.0.1:${port}`),
);
async function stop() {
  server.close();
  await db.end();
}
process.on('SIGTERM', stop);
process.on('SIGINT', () => stop().then(() => process.exit()));

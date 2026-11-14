export type Language = 'en' | 'fi' | 'sv';
export type Revision = {
  revision_id: number;
  parent_id: number;
  timestamp: string;
  user: string;
  comment: string;
  source?: {
    wiki: string;
    page_id: number;
    revision_id: number;
    url: string;
  } | null;
  url: string;
  diff_url: string;
};
export type Article = {
  language: Language;
  title: string;
  pageId: number;
  sourcePageId: number;
  anchorRevision: number;
  sourceAnchorRevision: number;
  anchorTimestamp: string;
  earliestTimestamp: string;
  revisionCount: number;
  sourceUrl: string;
  embeddingTruncated: boolean;
};
export type Topic = {
  id: string;
  title: string;
  summary: string;
  position: [number, number, number];
  articles: Record<Language, Article>;
  distances: { id: string; distance: number }[];
};
export type Catalog = {
  schemaVersion: number;
  topics: Topic[];
  topicCount: number;
  articleCount: number;
  model: string;
  dimensions: number;
};
export type SearchResult = {
  id: string;
  distance: number;
  matchedLanguage: Language;
  matchedTitle: string;
};
export const languageNames: Record<Language, string> = {
  en: 'English',
  fi: 'Suomi',
  sv: 'Svenska',
};
export const dateLabel = (value: string) =>
  new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value));
export const yearLabel = (value: string) =>
  new Date(value).getUTCFullYear().toString();

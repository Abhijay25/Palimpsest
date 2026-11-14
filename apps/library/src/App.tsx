import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Scene from './Scene.tsx';
import type {
  Catalog,
  Language,
  Revision,
  SearchResult,
  Topic,
} from './types.ts';
import { dateLabel, languageNames } from './types.ts';

function Arrow({ back = false }: { back?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      aria-hidden="true"
      style={back ? { transform: 'rotate(180deg)' } : undefined}
    >
      <path d="M4 12h15m-6-6 6 6-6 6" />
    </svg>
  );
}
function Close() {
  return (
    <svg
      viewBox="0 0 20 20"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      aria-hidden="true"
    >
      <path d="m5 5 10 10M15 5 5 15" />
    </svg>
  );
}
function Mark() {
  return (
    <svg
      viewBox="0 0 32 32"
      width="29"
      height="29"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
    >
      <path d="M5 5v22M12 5v22M19 5v22M26 5v22M4 7h24M4 25h24M8 3l15 26" />
    </svg>
  );
}
function SearchIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="8.5" cy="8.5" r="5.5" />
      <path d="m12.5 12.5 4 4" />
    </svg>
  );
}
const getJSON = async (url: string, options?: RequestInit) => {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.error)
    throw new Error(
      data.error || 'The Library could not respond. Please retry.',
    );
  return data;
};
const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));
const initialRoute = () =>
  new URLSearchParams(window.location.hash.replace(/^#/, ''));
function readRoute() {
  const params = initialRoute();
  const id = params.get('topic');
  const rawLanguage = params.get('lang') || 'en';
  const revision = params.get('revision');
  const view = params.get('view');
  let error = '';
  if (!['en', 'fi', 'sv'].includes(rawLanguage))
    error = 'This language is unavailable. Choose English, Finnish or Swedish.';
  else if (id && !/^Q\d+$/.test(id))
    error = 'This topic address is invalid. Choose a book from the library.';
  else if (view && view !== 'reader')
    error = 'This library view is unavailable.';
  else if (
    (view === 'reader' || revision) &&
    (!id ||
      !revision ||
      !/^\d+$/.test(revision) ||
      !Number.isSafeInteger(Number(revision)) ||
      Number(revision) <= 0)
  )
    error = 'This edition address is invalid. No edition was opened.';
  return {
    topic: error ? null : id,
    language: (['en', 'fi', 'sv'].includes(rawLanguage)
      ? rawLanguage
      : 'en') as Language,
    reading: !error && Boolean(id) && Boolean(view === 'reader' || revision),
    revision: !error && revision ? Number(revision) : null,
    error,
  };
}
function Languages({
  language,
  onChange,
  light = false,
}: {
  language: Language;
  onChange: (language: Language) => void;
  light?: boolean;
}) {
  return (
    <div
      className={'languages ' + (light ? 'languages-paper' : '')}
      role="group"
      aria-label="Article language"
    >
      {(['en', 'fi', 'sv'] as Language[]).map((lang) => (
        <button
          key={lang}
          aria-pressed={lang === language}
          onClick={() => onChange(lang)}
        >
          {languageNames[lang]}
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [initial] = useState(readRoute);
  const [routeError, setRouteError] = useState(initial.error);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(initial.topic);
  const [language, setLanguage] = useState<Language>(initial.language);
  const [versions, setVersions] = useState<Revision[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [versionError, setVersionError] = useState('');
  const [walk, setWalk] = useState(0);
  const [reading, setReading] = useState(initial.reading);
  const [readerTarget, setReaderTarget] = useState<number | null>(null);
  const [displayedRevision, setDisplayedRevision] = useState<Revision | null>(
    null,
  );
  const [announcement, setAnnouncement] = useState('');
  const [listView, setListView] = useState(
    () =>
      window.matchMedia('(prefers-reduced-motion: reduce), (max-width: 760px)')
        .matches,
  );
  const [webglFailed, setWebglFailed] = useState(false);
  const [about, setAbout] = useState(false);
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(
    null,
  );
  const [searchError, setSearchError] = useState('');
  const [routeVersion, setRouteVersion] = useState(0);
  const [transitionTopic, setTransitionTopic] = useState<string | null>(null);
  const transitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const iframe = useRef<HTMLIFrameElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const lastFocused = useRef<HTMLElement | null>(null);
  const requestedRevision = useRef<number | null>(initial.revision);
  const readingRef = useRef(reading);
  readingRef.current = reading;
  const languageChanged = useRef(false);
  const searchSequence = useRef(0);
  const topic = catalog?.topics.find((row) => row.id === selectedId) || null;
  const fallback = listView || webglFailed;
  const currentIndex = clamp(
    Math.round(walk),
    0,
    Math.max(0, versions.length - 1),
  );

  const updateRoute = useCallback(
    (id: string | null, lang: Language, revision?: number, replace = false) => {
      const params = new URLSearchParams();
      if (id) {
        params.set('topic', id);
        params.set('lang', lang);
        if (revision) {
          params.set('view', 'reader');
          params.set('revision', String(revision));
        }
      } else if (lang !== 'en') params.set('lang', lang);
      window.history[replace ? 'replaceState' : 'pushState'](
        null,
        '',
        window.location.pathname + (params.size ? '#' + params : ''),
      );
    },
    [],
  );
  const load = useCallback(() => {
    setCatalogError('');
    getJSON('/api/catalog')
      .then((data) => setCatalog(data))
      .catch((error) => setCatalogError(error.message));
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    const media = window.matchMedia(
      '(prefers-reduced-motion: reduce), (max-width: 760px)',
    );
    const change = () => {
      if (media.matches) setListView(true);
    };
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    const onRoute = () => {
      const route = readRoute();
      setRouteError(route.error);
      setLanguage(route.language);
      setSelectedId(route.topic);
      setReading(route.reading);
      setReaderTarget(null);
      setDisplayedRevision(null);
      requestedRevision.current = route.revision;
      setRouteVersion((value) => value + 1);
    };
    window.addEventListener('hashchange', onRoute);
    return () => window.removeEventListener('hashchange', onRoute);
  }, []);
  useEffect(() => {
    if (!catalog || !selectedId) return;
    if (!topic) {
      setRouteError(
        'This topic is outside the curated collection. No edition was opened. Choose a book from the library.',
      );
      setSelectedId(null);
      setReading(false);
      return;
    }
    const controller = new AbortController();
    setLoadingVersions(true);
    setVersionError('');
    setVersions([]);
    setReaderTarget(null);
    setDisplayedRevision(null);
    setWalk(0);
    const requested = requestedRevision.current;
    requestedRevision.current = null;
    getJSON('/api/topics/' + topic.id + '/revisions?lang=' + language, {
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        const rows: Revision[] = data.versions;
        setVersions(rows);
        setLoadingVersions(false);
        if (requested !== null) {
          const revision = rows.find((row) => row.revision_id === requested);
          if (!revision) {
            setVersionError(
              'The requested edition is unavailable. No other edition has been opened.',
            );
            return;
          }
          setReaderTarget(revision.revision_id);
          setDisplayedRevision(revision);
          setWalk(rows.indexOf(revision));
          setReading(true);
        } else if (readingRef.current) {
          const latest = rows.find(
            (row) =>
              row.revision_id === topic.articles[language].anchorRevision,
          );
          if (!latest)
            throw new Error('The latest imported edition is unavailable.');
          setReaderTarget(latest.revision_id);
          setDisplayedRevision(latest);
        }
        if (languageChanged.current) {
          setAnnouncement(
            'Language changed to ' +
              languageNames[language] +
              '. Showing the latest imported edition, ' +
              dateLabel(topic.articles[language].anchorTimestamp) +
              ' UTC.',
          );
          languageChanged.current = false;
        } else
          setAnnouncement(
            topic.articles[language].title +
              '. ' +
              rows.length +
              ' verified imported editions, newest to oldest.',
          );
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setLoadingVersions(false);
          setVersionError(error.message);
        }
      });
    return () => controller.abort();
  }, [catalog, selectedId, language, routeVersion]);

  function enterTopic(id: string) {
    if (transitionTimer.current) clearTimeout(transitionTimer.current);
    setRouteError('');
    setSearchResults(null);
    setSearchError('');
    setAbout(false);
    const arrive = () => {
      setTransitionTopic(null);
      setReading(false);
      setReaderTarget(null);
      setDisplayedRevision(null);
      setWalk(0);
      setSelectedId(id);
      updateRoute(id, language);
    };
    if (!fallback && !selectedId) {
      setTransitionTopic(id);
      setAnnouncement(
        'Entering ' +
          (catalog?.topics.find((row) => row.id === id)?.title || 'this book') +
          '…',
      );
      transitionTimer.current = setTimeout(arrive, 650);
    } else arrive();
  }
  function leaveTopic() {
    if (transitionTimer.current) clearTimeout(transitionTimer.current);
    setRouteError('');
    setTransitionTopic(null);
    setReading(false);
    setSelectedId(null);
    setVersions([]);
    setVersionError('');
    setWalk(0);
    updateRoute(null, language);
    setAnnouncement('Returned to the library.');
  }
  function openEdition(revision: Revision) {
    lastFocused.current = document.activeElement as HTMLElement;
    setDisplayedRevision(revision);
    setReaderTarget(revision.revision_id);
    setReading(true);
    updateRoute(selectedId, language, revision.revision_id);
  }
  const closeReader = useCallback(() => {
    setReading(false);
    setReaderTarget(null);
    updateRoute(selectedId, language);
    setTimeout(() => {
      if (lastFocused.current?.isConnected) lastFocused.current.focus();
      else
        document
          .querySelector<HTMLElement>(
            '.walking-controls button,.edition-list button,.back-button',
          )
          ?.focus();
    }, 20);
  }, [selectedId, language, updateRoute]);
  function switchLanguage(next: Language) {
    if (next === language) return;
    languageChanged.current = true;
    setReaderTarget(null);
    setDisplayedRevision(null);
    setVersions([]);
    setWalk(0);
    setAnnouncement(
      'Opening the latest imported ' + languageNames[next] + ' edition…',
    );
    setLanguage(next);
    updateRoute(selectedId, next);
  }
  useEffect(() => {
    if (reading) closeButton.current?.focus();
  }, [reading]);
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.source !== iframe.current?.contentWindow ||
        event.data?.topicId !== selectedId ||
        event.data?.language !== language
      )
        return;
      if (event.data.type === 'library:close') closeReader();
      if (event.data.type === 'library:edition') {
        const revision = versions.find(
          (row) => row.revision_id === event.data.revision,
        );
        if (revision && revision.timestamp === event.data.timestamp) {
          setDisplayedRevision(revision);
          updateRoute(selectedId, language, revision.revision_id, true);
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [selectedId, language, versions, closeReader, updateRoute]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).closest('input,textarea,select'))
        return;
      if (reading) {
        if (event.key === 'Escape') {
          event.preventDefault();
          closeReader();
        }
        return;
      }
      if (selectedId && versions.length) {
        if (
          [
            'ArrowDown',
            'ArrowUp',
            'PageDown',
            'PageUp',
            'Home',
            'End',
          ].includes(event.key)
        ) {
          event.preventDefault();
          setWalk((value) =>
            event.key === 'Home'
              ? 0
              : event.key === 'End'
                ? versions.length - 1
                : clamp(
                    value +
                      (['ArrowDown', 'PageDown'].includes(event.key) ? 1 : -1) *
                        (event.key.startsWith('Page') ? 4 : 1),
                    0,
                    versions.length - 1,
                  ),
          );
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          leaveTopic();
        }
      }
    };
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  }, [selectedId, versions.length, reading, closeReader]);
  async function search(event: FormEvent) {
    event.preventDefault();
    const sequence = ++searchSequence.current;
    setSearching(true);
    setSearchError('');
    setSearchResults(null);
    try {
      const data = await getJSON('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      if (sequence === searchSequence.current) setSearchResults(data.results);
    } catch (error) {
      if (sequence === searchSequence.current)
        setSearchError((error as Error).message);
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  }
  const revisionCount =
    catalog?.topics.reduce(
      (sum, row) =>
        sum +
        Object.values(row.articles).reduce(
          (count, article) => count + article.revisionCount,
          0,
        ),
      0,
    ) || 0;
  return (
    <>
      <div
        className={
          'application ' +
          (topic ? 'is-corridor' : 'is-overview') +
          (transitionTopic ? ' is-travelling' : '')
        }
        inert={reading || undefined}
      >
        {catalog && !fallback && (
          <Scene
            topics={catalog.topics}
            topic={topic}
            transitionTopic={transitionTopic}
            language={language}
            revisions={versions}
            walk={walk}
            paused={reading || loadingVersions}
            onWalk={setWalk}
            onTopic={enterTopic}
            onEdition={openEdition}
            onFailure={() => {
              setWebglFailed(true);
              setAnnouncement(
                '3D navigation is unavailable. The accessible library list is ready.',
              );
            }}
          />
        )}
        <div className="scene-vignette" aria-hidden="true" />
        <header className="app-header">
          <button
            className="brand"
            onClick={leaveTopic}
            aria-label="Palimpsest library home"
          >
            <Mark />
            <span>Palimpsest</span>
          </button>
          <form className="search-form" onSubmit={search} role="search">
            <SearchIcon />
            <input
              aria-label="Search the library by meaning"
              placeholder="A topic, a question, a connection…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={1000}
            />
            <button
              type="submit"
              disabled={searching || !query.trim()}
              aria-label="Search"
            >
              {searching ? <span className="spinner" /> : <Arrow />}
            </button>
          </form>
          <div className="header-actions">
            <button
              className="text-button"
              onClick={() => setListView((value) => !value)}
              aria-pressed={fallback}
            >
              {fallback ? 'Spatial view' : 'List view'}
            </button>
            <button
              className="about-toggle"
              aria-label="About this collection"
              aria-expanded={about}
              onClick={() => setAbout((value) => !value)}
            >
              i
            </button>
          </div>
        </header>
        {routeError && (
          <section className="corridor-status" role="alert">
            <p>{routeError}</p>
            <button className="primary-button" onClick={leaveTopic}>
              Return to the library <Arrow />
            </button>
          </section>
        )}
        {(searchResults || searchError || searching) && (
          <section className="search-results" aria-label="Search results">
            <div className="search-results-heading">
              <span>
                {searching
                  ? 'Finding connections…'
                  : searchError
                    ? 'Search unavailable'
                    : 'Connections in this collection'}
              </span>
              <button
                aria-label="Close search results"
                onClick={() => {
                  searchSequence.current++;
                  setSearching(false);
                  setSearchResults(null);
                  setSearchError('');
                }}
              >
                <Close />
              </button>
            </div>
            {searchError ? (
              <p role="alert">{searchError}</p>
            ) : searching ? (
              <p>Reading the meaning of your query with bge-m3…</p>
            ) : (
              <>
                <ol>
                  {searchResults?.map((result) => {
                    const row = catalog?.topics.find(
                      (candidate) => candidate.id === result.id,
                    );
                    return row ? (
                      <li key={result.id}>
                        <button onClick={() => enterTopic(row.id)}>
                          <span>
                            {row.title}
                            <small>
                              Matched the{' '}
                              {languageNames[result.matchedLanguage]} article
                            </small>
                          </span>
                          <Arrow />
                        </button>
                      </li>
                    ) : null;
                  })}
                </ol>
                <p className="search-note">
                  Closest matches among three curated topics. Search works
                  across English, Finnish and Swedish.
                </p>
              </>
            )}
          </section>
        )}
        {!catalog && (
          <div className="initial-state">
            <Mark />
            <h1>
              {catalogError
                ? 'The library is preparing.'
                : 'Opening the library.'}
            </h1>
            <p role={catalogError ? 'alert' : 'status'}>
              {catalogError || 'Connecting its books and their histories…'}
            </p>
            {catalogError ? (
              <button className="primary-button" onClick={load}>
                Try again <Arrow />
              </button>
            ) : (
              <span className="spinner" />
            )}
          </div>
        )}
        {catalog && !selectedId && !fallback && (
          <section className="introduction">
            <h1>
              Every word
              <br />
              <em>has a past.</em>
            </h1>
            <p>
              An endless-feeling library of real Wikipedia histories.
              <br />
              Find a connection. Step inside a book.
            </p>
            <div className="intro-cue">
              <span className="scroll-line" aria-hidden="true" />
              <span>Scroll to drift · choose a book to enter</span>
            </div>
          </section>
        )}
        {catalog && !selectedId && fallback && (
          <main className="catalog-view">
            <h1>
              A library
              <br />
              <em>through time.</em>
            </h1>
            <p>Three subjects. Three languages. Every imported edition.</p>
            <Languages language={language} onChange={switchLanguage} />
            <div className="catalog-list">
              {catalog.topics.map((row, index) => (
                <button
                  key={row.id}
                  className="catalog-row"
                  onClick={() => enterTopic(row.id)}
                >
                  <span
                    className={'mini-book mini-book-' + index}
                    aria-hidden="true"
                  />
                  <span>
                    <strong>{row.articles[language].title}</strong>
                    <small>
                      {row.articles[language].revisionCount} editions ·{' '}
                      {dateLabel(row.articles[language].anchorTimestamp)}
                    </small>
                  </span>
                  <Arrow />
                </button>
              ))}
            </div>
            <p className="list-note">
              {webglFailed
                ? '3D is unavailable in this browser. All books and their passage histories remain accessible.'
                : 'A quieter route through the same library. Switch to Spatial view for the 3D lattice.'}
            </p>
          </main>
        )}
        {selectedId && (
          <main
            className={
              'corridor-interface ' + (fallback ? 'corridor-fallback' : '')
            }
          >
            <div className="corridor-heading">
              <button className="back-button" onClick={leaveTopic}>
                <Arrow back /> The library
              </button>
              <h1>{topic?.articles[language].title || 'Unknown topic'}</h1>
              <div className="corridor-description">
                <span>
                  {versions.length
                    ? versions.length + ' real editions'
                    : 'Preparing edition history'}
                </span>
                <span className="dot" />
                <span>Newer at the entrance · older ahead</span>
              </div>
              <Languages language={language} onChange={switchLanguage} />
            </div>
            {(loadingVersions || versionError) && (
              <section
                className="corridor-status"
                role={versionError ? 'alert' : 'status'}
              >
                {loadingVersions ? (
                  <>
                    <span className="spinner" /> Opening verified editions…
                  </>
                ) : (
                  <>
                    <p>{versionError}</p>
                    <button
                      className="primary-button"
                      onClick={() => setRouteVersion((value) => value + 1)}
                    >
                      Retry history <Arrow />
                    </button>
                  </>
                )}
              </section>
            )}
            {!loadingVersions && !versionError && versions.length > 0 && (
              <>
                {fallback && (
                  <ol
                    className="edition-list"
                    aria-label="Editions, newest to oldest"
                  >
                    {versions.map((revision, index) => (
                      <li key={revision.revision_id}>
                        <button onClick={() => openEdition(revision)}>
                          <span className="edition-list-index">
                            {String(index + 1).padStart(2, '0')}
                          </span>
                          <span>
                            <strong>{dateLabel(revision.timestamp)}</strong>
                            <small>
                              {revision.user} · revision {revision.revision_id}
                            </small>
                          </span>
                          <Arrow />
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
                {!fallback && (
                  <div className="walking-controls">
                    <div className="walk-current">
                      <span>
                        At edition {String(currentIndex + 1).padStart(2, '0')}{' '}
                        <span className="walk-total">/ {versions.length}</span>
                      </span>
                      <strong>
                        {dateLabel(versions[currentIndex].timestamp)}
                      </strong>
                      <button
                        onClick={() => openEdition(versions[currentIndex])}
                      >
                        Open this edition <Arrow />
                      </button>
                    </div>
                    <div className="walk-track">
                      <button
                        aria-label="Return to newest edition"
                        onClick={() => setWalk(0)}
                      >
                        Newest
                      </button>
                      <input
                        aria-label="Walk through revision history"
                        type="range"
                        min="0"
                        max={versions.length - 1}
                        step=".01"
                        value={walk}
                        onChange={(event) =>
                          setWalk(Number(event.target.value))
                        }
                      />
                      <button
                        aria-label="Walk to oldest edition"
                        onClick={() => setWalk(versions.length - 1)}
                      >
                        Oldest
                      </button>
                    </div>
                    <p>
                      Scroll or use ↑ ↓ to walk · choose a dated book to read
                    </p>
                  </div>
                )}
              </>
            )}
          </main>
        )}
        {about && (
          <aside className="about-panel">
            <h2>
              A finite collection.
              <br />
              An infinite perspective.
            </h2>
            <p>
              This first library brings together {catalog?.topicCount || 3}{' '}
              topics, each in English, Finnish and Swedish. Its{' '}
              {revisionCount || 'original'} imported revisions are real public
              Wikipedia edits.
            </p>
            <p>
              Distance between topics comes from multilingual bge-m3 embeddings
              and MariaDB vector search. Walking through a book follows its
              actual revision order.
            </p>
            <p>
              Histories end at each article’s imported source snapshot. Some
              templates and generated text remain unavailable for attribution.
            </p>
            <p className="attribution">Wikipedia contributors · CC BY-SA 4.0</p>
          </aside>
        )}
        <footer className="app-footer">
          <span>
            {topic
              ? 'An archive of wording, one edition at a time.'
              : catalog
                ? catalog.topicCount +
                  ' topics · ' +
                  catalog.articleCount +
                  ' language articles · ' +
                  revisionCount +
                  ' editions'
                : 'A library through time'}
          </span>
          <span>
            Wikipedia contributors <span className="footer-divider">/</span> CC
            BY-SA 4.0
          </span>
        </footer>
      </div>
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
      {reading && topic && (
        <div
          className="reader-scrim"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeReader();
          }}
        >
          <section
            className="book-reader"
            role="dialog"
            aria-modal="true"
            aria-labelledby="book-title"
          >
            <span
              tabIndex={0}
              className="focus-sentinel"
              onFocus={() => {
                const nodes =
                  iframe.current?.contentDocument?.querySelectorAll<HTMLElement>(
                    'a[href],button,input,select,[tabindex="0"]',
                  );
                nodes?.item(nodes.length - 1)?.focus();
              }}
            />
            <header className="book-toolbar">
              <div className="book-heading">
                <span className="book-icon" aria-hidden="true">
                  <Mark />
                </span>
                <div>
                  <h2 id="book-title">{topic.articles[language].title}</h2>
                  <p>
                    {displayedRevision
                      ? dateLabel(displayedRevision.timestamp) +
                        ' UTC · revision ' +
                        displayedRevision.revision_id
                      : 'Opening the latest imported edition…'}
                  </p>
                </div>
              </div>
              <Languages language={language} onChange={switchLanguage} light />
              <button
                className="reader-close"
                ref={closeButton}
                onClick={closeReader}
                aria-label="Close book and return to corridor"
              >
                <Close />
              </button>
            </header>
            <div className="book-binding" aria-hidden="true" />
            <div className="book-pages">
              {readerTarget ? (
                <iframe
                  ref={iframe}
                  key={topic.id + language + readerTarget}
                  title={
                    topic.articles[language].title + ' article and inline Blame'
                  }
                  src={
                    '/reader/' + topic.id + '/' + language + '/' + readerTarget
                  }
                  sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
                />
              ) : (
                <div className="reader-loading">
                  {versionError ? (
                    <p role="alert">{versionError}</p>
                  ) : (
                    <>
                      <span className="spinner" />
                      <p>Opening this edition…</p>
                    </>
                  )}
                </div>
              )}
            </div>
            <footer className="book-footer">
              <span>Select a passage to follow its history.</span>
              <nav aria-label="Original article links">
                {displayedRevision && (
                  <a
                    href={displayedRevision.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open in Palimpsest <span aria-hidden="true">↗</span>
                  </a>
                )}
                {displayedRevision?.source?.url && (
                  <a
                    href={displayedRevision.source.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original Wikipedia edition{' '}
                    <span aria-hidden="true">↗</span>
                  </a>
                )}
              </nav>
            </footer>
            <span
              tabIndex={0}
              className="focus-sentinel"
              onFocus={() => closeButton.current?.focus()}
            />
          </section>
        </div>
      )}
    </>
  );
}

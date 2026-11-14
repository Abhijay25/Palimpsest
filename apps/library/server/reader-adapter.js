/* Explicit standalone host for the repository's native Blame consumer. */
(async function () {
  'use strict';
  var context = JSON.parse(
    document.getElementById('reader-context').textContent,
  );
  var origin = window.location.origin;
  var api = origin + '/api/wiki/' + context.language;
  var csrf = null;
  var realFetch = window.fetch.bind(window);
  function announce(type, extra) {
    window.parent.postMessage(
      Object.assign(
        { type: type, topicId: context.topicId, language: context.language },
        extra || {},
      ),
      origin,
    );
  }
  function readerUrl(revision) {
    return (
      origin +
      '/reader/' +
      context.topicId +
      '/' +
      context.language +
      '/' +
      revision
    );
  }
  var originalConfig = {
    wgPageName: context.title,
    wgRevisionId: context.revision,
    wgArticleId: context.pageId,
    wgCanonicalSpecialPageName: null,
  };
  window.mw = {
    config: {
      get: function (keys) {
        return Array.isArray(keys)
          ? Object.fromEntries(
              keys.map(function (key) {
                return [key, originalConfig[key]];
              }),
            )
          : originalConfig[keys];
      },
    },
    util: {
      wikiScript: function () {
        return api;
      },
      getUrl: function (title, params) {
        if (params && params.action === 'blame')
          return readerUrl(params.oldid || context.latestImported);
        return (
          context.wiki +
          '/index.php?' +
          new URLSearchParams(Object.assign({ title: title }, params || {}))
        );
      },
    },
    user: {
      tokens: {
        get: function (key) {
          return key === 'csrfToken' ? csrf : null;
        },
      },
    },
  };
  window.fetch = async function (input, options) {
    var response = await realFetch(input, options);
    if (String(input).startsWith(api)) {
      response
        .clone()
        .json()
        .then(function (payload) {
          var result = payload.palimpsestblame;
          if (
            result &&
            result.status === 'ready' &&
            result.snapshot &&
            context.revisions.includes(result.snapshot.revision_id)
          ) {
            announce('library:edition', {
              revision: result.snapshot.revision_id,
              timestamp: result.snapshot.timestamp,
              source: result.snapshot.source,
              coverage: result.coverage,
            });
          }
        })
        .catch(function () {});
    }
    return response;
  };
  function repairArticleLinks() {
    var article = document.querySelector('.mw-parser-output');
    if (!article) return;
    article.querySelectorAll('a[href]').forEach(function (anchor) {
      var href = anchor.getAttribute('href');
      var resolved = new URL(href, context.wiki);
      var targetTitle =
        resolved.searchParams.get('title') ||
        decodeURIComponent(
          resolved.pathname.split('/index.php/')[1] || '',
        ).replaceAll('_', ' ');
      if (
        href.startsWith('#') ||
        (resolved.origin === new URL(context.wiki).origin &&
          resolved.hash &&
          targetTitle === context.title)
      ) {
        anchor.href = window.location.href.split('#')[0] + resolved.hash;
        anchor.target = '_self';
      } else if (href.startsWith('/') || href.startsWith('./')) {
        anchor.href = resolved.href;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
      } else if (/^https?:/.test(href)) {
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
      }
    });
    article.querySelectorAll('img[src]').forEach(function (img) {
      var src = img.getAttribute('src');
      if (src.startsWith('/')) img.src = new URL(src, context.wiki).href;
      img.loading = 'lazy';
    });
    article.querySelectorAll('.pb-attributed').forEach(function (span) {
      if (!span.textContent.trim()) {
        span.removeAttribute('tabindex');
        span.removeAttribute('role');
        span.classList.add('pb-whitespace');
      }
    });
    var root = document.getElementById('palimpsest-blame');
    var breakdown = root.querySelector('.pb-breakdown');
    if (breakdown && root.firstElementChild !== breakdown) {
      root.prepend(breakdown);
      breakdown.scrollIntoView({ block: 'nearest' });
    }
    root.querySelectorAll('.pb-warning').forEach(function (warning) {
      if (warning.textContent === 'generated-or-transcluded-content')
        warning.textContent =
          'Some template or generated content has no verified passage attribution.';
    });
    updateInspectVisibility();
  }
  var observer = new MutationObserver(repairArticleLinks);
  observer.observe(document.getElementById('mw-content-text'), {
    childList: true,
    subtree: true,
  });
  var inspect = document.createElement('button');
  inspect.type = 'button';
  inspect.className = 'reader-inspect';
  inspect.textContent = 'Inspect selected text';
  inspect.hidden = true;
  document.body.appendChild(inspect);
  function updateInspectVisibility() {
    if (!inspect) return;
    inspect.hidden =
      !document.querySelector('.pb-action-bar') ||
      Boolean(document.querySelector('.pb-breakdown'));
  }
  // Chromium otherwise collapses a drag across separately focusable word spans.
  // Keep native keyboard semantics at rest and restore them after pointer selection.
  var pointerWords = [];
  function restoreWordFocus() {
    pointerWords.forEach(function (entry) {
      if (entry.node.isConnected) {
        entry.node.setAttribute('role', entry.role);
        entry.node.setAttribute('tabindex', entry.tabindex);
      }
    });
    pointerWords = [];
  }
  document.addEventListener(
    'pointerdown',
    function (event) {
      restoreWordFocus();
      if (
        event.button !== 0 ||
        !event.target.closest('.mw-parser-output [data-pb-start]')
      )
        return;
      document
        .querySelectorAll(
          '.mw-parser-output .pb-attributed[role="button"][tabindex]',
        )
        .forEach(function (node) {
          pointerWords.push({
            node: node,
            role: node.getAttribute('role'),
            tabindex: node.getAttribute('tabindex'),
          });
          node.removeAttribute('role');
          node.removeAttribute('tabindex');
        });
    },
    true,
  );
  document.addEventListener('pointerup', restoreWordFocus, true);
  document.addEventListener('pointercancel', restoreWordFocus, true);
  window.addEventListener('blur', restoreWordFocus);
  inspect.addEventListener('mousedown', function (event) {
    event.preventDefault();
  });
  inspect.addEventListener('pointerdown', function () {
    document
      .querySelector('.pb-action-bar .pb-primary')
      ?.dispatchEvent(new Event('pointerdown'));
  });
  inspect.addEventListener('click', function () {
    document.querySelector('.pb-action-bar .pb-primary')?.click();
  });
  document.addEventListener('selectionchange', updateInspectVisibility);
  document.addEventListener(
    'keydown',
    function (event) {
      if (event.key === 'Escape' && !document.querySelector('.pb-breakdown'))
        announce('library:close');
    },
    true,
  );
  document.addEventListener('click', function (event) {
    var anchor = event.target.closest('a[href]');
    if (
      anchor &&
      anchor.origin === origin &&
      anchor.pathname.startsWith('/reader/')
    )
      return;
    if (anchor && anchor.origin !== origin) {
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
    }
  });
  try {
    var tokenResponse = await realFetch(
      api + '?action=query&meta=tokens&type=csrf&format=json&formatversion=2',
      { credentials: 'same-origin' },
    );
    var tokenData = await tokenResponse.json();
    csrf =
      tokenData.query &&
      tokenData.query.tokens &&
      tokenData.query.tokens.csrftoken;
  } catch (error) {
    /* Read-only analysis still works; preparation retains the native error state. */
  }
  var script = document.createElement('script');
  script.src = origin + '/api/native/controller.js';
  script.onerror = function () {
    document.querySelector('#palimpsest-blame').textContent =
      'Passage history could not load. Close and reopen this edition to retry.';
  };
  document.head.appendChild(script);
})();

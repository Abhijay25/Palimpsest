# Wikipedia-style local defaults

The local FI/SV/EN runtime keeps upstream MediaWiki 1.46.2 and Vector 2022.
Defaults were compared on 2026-11-15 with Wikimedia's production
[CommonSettings.php](https://github.com/wikimedia/operations-mediawiki-config/blob/master/wmf-config/CommonSettings.php)
and [InitialiseSettings.php](https://github.com/wikimedia/operations-mediawiki-config/blob/master/wmf-config/InitialiseSettings.php).
This is a compatible local configuration, not a copy of Wikimedia's production infrastructure.

Changes:

- Remove the legacy Blame navigation hook; existing attribution data, jobs and API remain available.
- Use standard Vector text size, light appearance and limited article width. Saved user preferences take precedence.
- Match current thumbnail steps and the 330-pixel default, with a MediaWiki 1.46 preference compatibility list.
- Match watchlist/recent-change defaults: three watchlist days, one recent-change day, ordinary grouped-list defaults, watch new pages but do not automatically watch every edit.
- Match the ordinary Vector width exceptions for history/edit/diffs and login/account/preferences pages, with Swedish gallery dimensions.
- Enable the already-bundled MultimediaViewer, PageImages, TextExtracts, CiteThisPage, CategoryTree, ImageMap, Poem and SyntaxHighlight components. No extra packages or services are downloaded.
- Use Article / Artikkeli / Artikel for the main article namespace navigation.

The deliberate local differences remain: Palimpsest branding, native Issues,
authenticated review/scan rights, explicit inference controls, source attribution
and import limitations, local accounts, disabled email, separate job runners and
localhost-only services. Wikimedia central login, production search, mobile
frontend, page-preview service and site-specific gadgets are not provisioned by
this settings change. The existing responsive Vector fallback remains in use.

The owned runtime's settings and extension inventory were refreshed using its
idempotent setup command. The existing 60 runtime/import/rendering regressions,
48 targeted native/flags/evidence/article regressions, JavaScript navigation and
control checks, native Issues PHP checks and 27 attribution fixtures passed.
Docker's VM disconnected during the reload and was restarted; the owned database
completed crash recovery and wiki services returned healthy. Earlier exact-source
rendering and browser evidence is recorded in [native acceptance](native-issues.md).
Fresh post-settings article/media interaction checks must be distinguished from
that earlier evidence; service health alone is not a new visual-parity claim.

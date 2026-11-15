# Native article Issues

This implementation extends the digest-pinned upstream MediaWiki image. It does
not replace core, merge NeoWikiReview, remove the Flask previews, or migrate
preview review markers into authenticated decisions. Native parity requires the
acceptance work below; PHP lint or a page loading is not acceptance.

## Boundaries

* `PalimpsestIssues` adds `action=issues`, an article navigation tab and the
  `palimpsestissues` action API. The normal Article tab remains MediaWiki's full
  article renderer, including imported templates, Cite and Scribunto.
* The private `native_issues_server.py` is an HTTP service independent of a Flask
  application. It shares `issues.py`, exact evidence presentation and detector
  persistence with the previews. There is no iframe or redirect to a preview
  when the native action renders a list or evidence.
* Native browser reads go through MediaWiki read permission. Review and scans
  require registered native users, separate rights and POST with native CSRF.
  Ordinary registered users have `palimpsest-review`; only sysops have
  `palimpsest-scan` by default. Local administrators can change these groups.
* Server-to-server requests use a private random secret and HMAC-SHA256 over the
  exact timestamp/body, with a 60-second validity window. No browser receives
  the secret or provider credentials. Use a private host/network; the Python
  service publishes no CORS interface and rejects unsigned requests.
* `unified_native_review` uses MariaDB system versioning, keyed by native wiki,
  exact observation and edition, recording the native numeric reviewer ID.
  Preview markers remain in `unified_review`. Set `PalimpsestIssuesWikiId` to a
  stable unique identifier when moving a wiki between canonical addresses;
  otherwise it derives from canonical server, database name and table prefix.

## Identity and rendering

The extension reads the existing checksum-verified per-language provenance
bundles produced by `scripts/blame_provenance.py`. It checks title, local page,
source page, source revision, local revision, local parent, timestamp, readable
content and SHA-256. Source IDs never become `oldid` directly. Exact-source
links resolve through `action=issues&source=...` and redirect to core with the
verified local `oldid`, retaining the Issues/return preset.

An exact imported revision may be readable even when the rest of an import is
incomplete; this does not establish complete history. Unimported or changed
revisions fail explicitly. Normal scans require a reconciled selected revision;
edit scans also require its exact reconciled parent. Detector source text must
match the native content hash before using its result. A successful archived
assessment remains readable if a working JSON/download cache disappears. Paid
rescans require an explicit fresh action; pending storage recovery is reused.

The native page-consistency view obtains its article HTML from MediaWiki's
parser for the exact local revision. Full article links use core's article
view. Historical transclusions/media can reflect imported dependency versions;
they are not claimed to reproduce the historical source site's full template
environment. Missing dependencies must be addressed by the existing explicit
support acquisition/import path, not hidden by a current snapshot or excerpts.

Evidence uses the same word diff, source anchoring, unanchored tray, desktop
collision layout and mobile popover code as the preview. `scripts/sync_issues_assets.py`
copies these assets for ResourceLoader; `--check` fails if they diverge. Both
surfaces remain runnable until the user explicitly accepts native parity.

## Setup on an owned runtime

Do not apply this setup to another checkout's running experiment. Inspect the
runtime ownership and disk space first. Keep the runtime's existing disk guard.

1. With the installed research interpreter, explicitly run `issues.py init` in
   `tools/language-gap-explorer`. This adds the native marker table; it does not
   backfill or assess anything. Existing source records are unchanged.
2. Set up a separately owned wiki runtime using `scripts/runtime.py`, then use
   the repository's corpus/history/support import and verification commands.
   Export/install its verified provenance bundles with
   `scripts/blame_provenance.py --data-root ... --manifest ... --install`.
3. Run `scripts/native_issues.py --app-python <existing-research-python>
   --research-root <existing-research-root> --secret-file <private-bridge-secret>`.
   The launcher creates a random bridge secret if absent, without printing it.
   It starts only the bridge; no schema/import/model/inference work runs on
   startup. On this Docker Desktop installation, the default localhost listener is
   reachable through host.docker.internal; no all-interface listener is needed.
4. Supply `PALIMPSEST_ISSUES_SERVICE_URL`, `PALIMPSEST_ISSUES_SECRET_FILE` and
   optionally `PALIMPSEST_ISSUES_EXPLORER_URL` when applying
   `infra/wiki/compose.issues.override.yaml` to that owned runtime. The secret is
   mounted read-only; upstream images remain pinned. The URL is server-to-server.
5. Configure `PALIMPSEST_NATIVE_WIKIS` on the explorer process as a JSON map of
   edition to its actual native `index.php` URL. The bridge launcher can accept
   the same map via `--native-wikis`. No wiki hostname, local revision ID or
   imported title is guessed. Until configured, the preview continues to be the
   explorer's explicitly interim destination.

### Optional real rendering dependencies

`infra/wiki/extensions/rendering.lock.json` pins the official complete REL1_46
Wikibase, CLDR, Labeled Section Transclusion and GeoData distributions by commit and archive SHA-256. Explicitly prepare
them with `scripts/prepare_wiki_rendering.py --component wikibase` and
`--component cldr` / `--component lst` / `--component geodata`. Preparation does not enable extensions in a running wiki.
`--check` verifies the entire extracted package against its pinned archive
without downloading. Changed or unregistered existing files are preserved and
rejected rather than overwritten. The complete Wikibase archive includes its
real PHP and JavaScript dependencies; no stub data library is used.

Apply `infra/wiki/compose.rendering.override.yaml` only to the explicitly owned
runtime, supplying `PALIMPSEST_WIKIBASE_ROOT`, `PALIMPSEST_CLDR_ROOT`, `PALIMPSEST_LST_ROOT` and `PALIMPSEST_GEODATA_ROOT` as
absolute prepared directories. Run the standard MediaWiki schema updater for
each owned wiki before enabling the profile. This keeps core images pinned and
mounts the packages read-only. Startup validates preparation markers and pins;
it never installs packages or acquires source data.

The rendering profile also enables core's ForeignAPIRepo for the source edition,
alongside Commons. This restores real files hosted only on that Wikipedia and
keeps the source file description/licensing links. Metadata and descriptions are
cached; thumbnails stay remote (`fileCacheExpiry=0`), avoiding query-bearing SVG
thumbnail filenames on the Windows-mounted filesystem. Media are source reads,
not historical media snapshots. Labeled Section Transclusion handles the source
templates' section tags using the [official extension](https://www.mediawiki.org/wiki/Extension:Labeled_Section_Transclusion).

`scripts/acquire_wikidata.py` explicitly captures a bounded set of real public
entities and optional one-hop references. Captures retain source entity/revision,
modified time, acquisition time, URL and content hash. `scripts/import_wikidata.py`
uses the official entity deserializer/store and reconciles the native serialized
entity back to the captured content, recording distinct source/local revisions.
Changed captures or differing existing native entities fail without replacement.
Captured entity namespaces have no web-edit right assigned by default. Client
sitelinks use the source language wiki ID; Issues reviewer scope continues to
use its separate native installation identity.

An owned runtime can retain these options in its private
`<data-root>/native-profile.json`: schema version 1, its exact `project`,
`overrides: ["issues", "rendering"]`, and an `environment` object containing only
the three Issues variables above plus the four rendering roots. Store the secret
file path, never the secret value. `runtime.py ... up` reapplies this profile;
unknown overrides, project mismatches and image override variables are rejected.
The verified installation uses:

```text
python scripts/runtime.py --project palimpsest-issues-native --data-root .local/wiki-issues --ports 18091,18092,18093 up
```

## Histogram contract

The existing read-only matrix path now includes all nine detector kinds:
`FACT`, `FRAMING`, `MOTIVE`, `REMOVED_CONTEXT`, `HIDDEN_TEXT`, `CITATION_DATE`,
`CITED_PAGE`, `CHERRY_PICK`, `OUT_OF_SYNC`. These remain distinct from lowercase
language `framing`, `coverage`, `contradiction`. Names accompany the color keys;
the detector menu exposes independent classification toggles.

Language buckets retain observation checkpoint time and strongest actual
selected-pair categories. Detector buckets use the source revision's edit time.
Their assessment time stays separate on the evidence/list and in metadata. A
scan in 2026 of a 2020 revision belongs to the 2020 source-time bucket; it is not
evidence of continuous assessment from 2020 to 2026. Undated detector records
are reported outside the histogram rather than assigned the scan date.

Counts remain period unions of original issue identities, never a sum of
observations or a grouping by prose title. Original language run/group and exact
occurrence identity remain intact, including weaker historical occurrences.
Detector successful-empty assessments, partial results, failed/running attempts
and unassessed source periods are separately exposed. Prior successful evidence
survives failed attempts. Detector-only history can be viewed without preparing
a language run; an explicitly missing language run is never substituted.

When native URLs are configured, bucket clicks open the native period-scoped
Issues list. Finding clicks resolve an exact native observation/occurrence. The
preset contains date window, languages, origin/classifications, original run and
exact evidence identity where relevant. Browser Back restores the explorer's
window, filters, bucket and selected finding, including detector observation ID.
Reads, evidence, navigation and histogram aggregation never start inference.

Bar clicks preserve the origin histogram's state and browser history entry;
the selected period is applied only to the native article's Issues list. They
do not first render the explorer's internal question list. Both browser Back
and Back to history explorer restore the histogram with its prior zoom/filters.
Older bucket-list return URLs without an exact selected finding normalize to
that histogram too. Existing exact finding deep links retain their identity.
`node tools/language-gap-explorer/test_bucket_navigation.js` exercises monthly
and yearly routing, the date clamp, filters, original history preservation,
legacy bucket URLs and exact finding compatibility. A real July bar journey
verified native date filters and both return paths, with the histogram visible
and the explorer's internal list hidden after returning.

## Acceptance record

The owned `palimpsest-issues-native` runtime is installed under
`.local/wiki-issues`, independently of the other checkout's NeoWikiReview
runtime. FI/SV/EN use localhost ports 18091/18092/18093. Images remain pinned;
the existing startup disk guard was retained. Shell runtime files use LF endings,
and first-language setup no longer requires uninstalled language configs.

Exact body reconciliation succeeded for EN source 1299995839/1301539037/1303580599
(local revisions 2/3/4), FI 23500447 (local 2) and the actually cited 23400367 (local 138),
and SV 57814003 (local 2).
These are explicitly selected issue-source revisions, not complete histories.
`scripts/import_issue_sources.py` accepts a bounded source dependency budget,
checkpoints source throttling, preserves source timestamps/hashes, and refreshes
only its selected runtime's derived parser caches after imports. The explicit
`--support-current` mode uses current source transclusions, separately labeled;
it never substitutes the historical article body. Static closure alone does not
establish complete rendering. Dynamic Lua dependencies require parser checks.
Imported SHORTDESC metadata is retained as a separate local page property with
no visible article text; its compatibility hook yields to an installed handler.

The owned runtime now runs the real official Wikibase Repo/Client at
`f4439bff9baebaa027a7b37be2bcaa8019b8f861` and CLDR at
`db24690ec0c55a85a7b056392faaf2e2e3b88d04`, plus Labeled Section Transclusion
`6b9718fc13963b5f29fccf3d62186af6b12537b1`, and GeoData at
`7729d9528c7b1eef717551eed37a655a676317ce`. GeoData's real schema updater ran
successfully in each owned wiki. All three native stores contain 143
reconciled captured entities (96 properties and 47 items), including Q134949
source revision 2544984464 and Q1001762. The capture is a bounded source-data snapshot, not
the entire Wikidata ontology or the structured-data environment in July 2025.
CLDR supplies translated citation language names. Ordinary runtime restart was
verified to preserve the rendering profile and existing source data.

Native parser checks for EN source 1301539037/local 3, FI 23400367/local 138 and
SV 57814003/local 2 returned respectively 50/45/17 sections and 359/178/18
reference markers, matching separately captured source parser responses for the
same revisions. None returned Lua errors. The EN `Template:Russian Conflicts`
redlink also occurs in its source parser response. Native browser inspection
confirmed the English infobox and all article images loaded, exact oldid=3,
and a visible revision-specific Wikipedia attribution link. These are structural
and selected-media checks; matching counts alone does not prove full fidelity.
Source templates suppress some notes when linked pages do not exist locally.
Importing the real linked source pages and dynamic Portal image modules restored
all seven English See-also notes and portal links; no placeholder pages or
rewritten source templates were used. Static traversal remains incomplete.

Finnish browser checks now load all 39 article images, including the two files
hosted outside Commons, and preserve the source's a/b explanatory-note labels.
The real source Cite label message was imported as a native system message.
Only the four explicitly selected Cite label-message identities are permitted by
that import exception; arbitrary system messages are not allowed. Scoped Finnish
infobox rules, attributed to Common.css source revision 24320334, restore desktop
placement and fit a 390-pixel mobile viewport without page overflow. They are a
selected style adaptation, not a complete import of source-site global styles.

A local diagnostic comparison of independently captured parser responses omits
styles/scripts, the table of contents, edit controls and citation backlinks from
its word stream. Finnish and Swedish normalized text match exactly. The English
footer labels (Outline/Index/Bibliography/Category) are restored using the real
target and redirect pages; its remaining text difference is spacing around a
romanization label. Citation backlink controls differ between source/native
renderers and are excluded explicitly; citation bodies and in-prose markers are
retained. Image-element counts match source responses: EN 45, FI 39, SV 27.
These diagnostics are not a substitute for complete visual/interaction acceptance.
`scripts/compare_wiki_rendering.py` reproduces the offline diagnostic from saved
parser responses and requires separate explicit source/local revision IDs. It
rejects mismatched IDs/titles and reports missing prose, media counts, headings
and error nodes without making a visual-parity claim.

The Swedish native browser also loaded all 27 images, had no parser errors,
and followed an in-prose citation to its actual note. Subsequent mobile checks
verified an actual 390-pixel viewport for English and Swedish Winter War:
document width 375 pixels, article content about 327 pixels and all images loaded.
Finnish Winter War and Mänttä also fit that viewport, with all images loaded.
These measurements use the selected browser tab after the viewport override;
the earlier unsuccessful desktop-width measurement was not accepted as mobile proof.

Real native API checks returned 135 latest language findings and three saved
flags. An authenticated native admin marked and undid a review; independent
reads confirmed persisted state, with the final marker unreviewed. Real POST
cached revision scans returned three saved flags for EN source 1301539037,
local 3 and exact source/local parent 1299995839/local 2. Cached page consistency
returned its saved successful empty result for the same revision. Native parsed
page results carry their own ResourceLoader dependencies and content hooks, so
Cite/media behavior is initialized when the saved page is inserted. A separate
native bridge path skips the redundant source/preview HTML renderer entirely;
only MediaWiki supplies the exact local parser output. The preview retains its
existing renderer by default. The final real saved-page API read returned local
3/source 1301539037, zero flags and 359 reference markers in about 1.9 seconds,
with the assessment fingerprint and provider ledger unchanged around that check.
An automated native bridge case makes the preview renderer fail if invoked.
A separate
read-only saved-page action does not require scan permission. The anonymous
native browser loaded the real saved empty page result with 359 reference
markers, while new-check controls remained disabled; no console errors occurred. A fresh scan
was blocked by the temporary cached-only verification guard. No provider calls
were made for acceptance. After these guarded checks, the bridge was restarted
with normal explicit account-permission checks; browsing still never scans. Read routes, missing imports and errors preserve prior
successful evidence. After installing Wikibase/CLDR, real authenticated native
review/undo also verified that changing an EN marker leaves the same FI
observation unreviewed; the final EN marker was restored to unreviewed. Ordinary
accounts can review but cannot scan, and captured entity pages cannot be edited
through the web. Cross-wiki/edition reviewer isolation and system-versioned undo
history also passed against isolated database tables.

Native browser checks verified styled exact-source evidence, collision-managed
desktop comments, highlighted passage navigation and a mobile anchored popover.
The shared assets now declare their own box sizing rather than depend on the
preview shell. Mobile comparisons can stack without an inline grid override.
A real histogram month click opened the native period/language/classification
preset. Bucket links retain the original analysis run; history filtering keeps
that run's language cohort alongside detector evidence. A real language finding click retained run/group/checkpoint/classification and
exact occurrence/observation in native Issues. Its full-article link resolved
source 1301539037 to core oldid=3, with 50 sections and 359 reference markers;
this verifies identity and structure, not error-free rendering. The return link
restored the exact occurrence, selected pair/classification, period and zoom. Configured
foreign-edition links resolve independently through each wiki.

Additional real navigation verification selected the weaker coverage occurrence
`dc72c8487c7bd60135181f686a77a18be41a53eda9c2a73c0c8bd85774cc3f69`
in the current run's foreign-volunteers group, which also has a stronger framing
occurrence at the same checkpoint/pair. The explorer's restored evidence link
now uses the configured native destination too, retaining exact occurrence,
classification and return state. Its native round trip preserved the weaker
coverage identity. A real month click retained the original run and selected
classifications; the native history list explicitly counts observations rather
than claiming the histogram's period-union count.

Missing explicit check revisions now show an unavailable selection instead of
defaulting to another imported revision. After changing the selector, both the
Read tab and full-article link resolve the newly selected source ID. A real
1299995839 selection opened local oldid=2 with its matching Wikipedia attribution.
Returning from an exact language finding to Issues clears its legacy group and
checkpoint selectors, preventing an immediate redirect back to the same finding.
Explicit checks take precedence over retained finding context.

Core historical `oldid` navigation now resolves through the verified local-to-source
mapping before opening Issues. A real mobile journey from EN local oldid=3
through Issues and Check for new issues retained source 1301539037 and its saved
three flags. An unmapped local revision retains an explicit unavailable selector;
it cannot default to another source revision. Source-resolution redirects also
replace stale revision context with the exact resolved source ID.

Opening explorer evidence no longer automatically starts an uncached local
translation. Only the explicit translation button does so; cached translations
remain readable without generation. `node tools/language-gap-explorer/test_translation_controls.js`
executes this behavior, including opening, explicit generation and hiding cached text.
Expand-surrounding-evidence controls appear only for evidence modes that support
expansion; complete exact-source article links remain available for other modes.

Native API checks rejected mismatched run/classification selections, anonymous
scan/review POSTs even with a valid anonymous CSRF token, and forged bridge
signatures (HTTP 403). Missing imports refused current-snapshot fallback. The
successful assessment payload hashes and provider-ledger row count stayed
unchanged around these navigation/error checks.

A controlled private-bridge detector outage, with new inference guarded off,
returned unavailable readiness while retaining three saved revision flags and
the saved empty page check with all 359 native reference markers. The real
anonymous browser could read both during the outage. Normal detector connection
and permission-gated explicit scans were then restored; Retry connection showed
ready without losing the displayed saved result. The public detector and both
previews were not stopped for this check.

Automated checks passed: 197 research checks (four opt-in DB cases skipped),
14 isolated Issues database checks, 60 runtime/import/rendering checks in the pinned Linux
image, 60 mocked detector API/page-consistency checks, 15 independent-viewer
checks, native PHP identity/readability/hash/CSRF/metadata tests, shared asset
equality, JavaScript histogram/calendar/syntax checks and native navigation
checks (`node infra/wiki/extensions/PalimpsestIssues/tests/navigation.js`). Later code changes
must rerun the relevant checks; no live paid detector accuracy evaluation is
implied by these results.

The positive page-card interaction was additionally verified in the real native
browser with `scripts/verify_native_page_fixture.py`: a temporary signed,
read-only bridge wrapper supplies two prominently labeled UI test annotations
only after the normal exact-source cached read succeeds. It blocks every scan
and review before dispatch, never saves its annotations and strips real assessment
identity from the decorated response. The real native parser still supplies the
article. This caught and repaired shared page-card explanations being hidden by
the collapsed-card CSS. Explanations now remain visible, Enter/click highlights
the actual quote, and absent quotes receive explicit unanchored feedback.
Desktop and an actual 390-pixel native viewport verified these behaviors, with
359 native reference markers retained. The normal bridge was then restored;
the browser returned to its real successful-empty result with zero page flags
and ready status. Neither synthetic annotation was inserted into the index or
cached as detector evidence. `test_native_page_fixture.py` checks isolation and
mutation rejection; `test_page_controls.js` executes visible explanations,
keyboard activation and missing-anchor feedback. These are UI fixture checks,
not positive detector accuracy evidence.
After the final page-card and renderer changes, 48 relevant native/flags/evidence/
article regression checks passed, along with both page-control JavaScript checks,
native navigation/histogram checks and shared asset equality. Two additional
standard-library fixture-isolation tests passed separately.

An additional real snapshot walkthrough now uses Mänttä (Q1001762), whose saved
findings already existed in the research index. Exact FI 23176523/local 248 and
SV 52985060/local 214 were imported and reconciled without new assessments.
The native list returns its two saved findings. The Swedish native evidence
view preserves SV-first comparison order, two anchored comments, disabled
anonymous review and the explicit unknown snapshot observation date. Its known
source-edit date (2023-05-30) remains separate from the assessment date. The
full-source link opens local oldid=214 with matching public-source attribution.
Native details now label historical checkpoints, unknown snapshot observation
dates and detector source edits separately, and show known source-edit dates
beside source revisions. Missing dates are filled only from verified local
provenance in presentation metadata; archived assessments remain unchanged.

The additional Mänttä comparison exposed real rendering gaps that have now been
repaired with official GeoData, actual coordinate display/formatter dependencies,
the real Finnish redirect syntax and captured municipality data. Both editions'
normalized article and citation text now match their exact source parser responses,
with no parser errors or missing-template links. FI has 11 sections/11 images;
SV has 6 sections/6 images. The native Finnish page displays municipality code
506 from captured P1203 and publishes its coordinates through MediaWiki's native
coordinates API. All 11 Finnish images load on desktop and mobile; the two SVG
thumbnails that failed when locally proxied now use their real remote thumbnails.
These checks cover the executed article render, not complete static dependency
closure or a historical reconstruction of the source template environment.

Native parity is still unaccepted. Remaining acceptance includes full
visual/interaction acceptance in all three editions. A
positive page-consistency finding is not present in the real cached native
sample; its native interaction has the explicitly synthetic browser check above,
not a real positive detector-result walkthrough. Fresh paid detector execution/accuracy was not
evaluated. Source acquisition encounters Wikimedia 429 responses
and retains resumable checkpoints. Static support closure remains incomplete;
actual source/native parser comparisons are required to distinguish executed
dependencies from unused or dynamic names. EN Portal namespace metadata and
three real dependent ship pages were imported from source. Native article bodies,
reference text and media now have the diagnostic/browser checks above; full
layout/interaction acceptance remains under verification.
Unavailable historical revisions
stay explicitly unavailable. Keep the runnable previews until the user verifies
complete content and interaction parity in MediaWiki.

See [the requirement-by-requirement delivery audit](native-issues-acceptance.md)
for the implementation, verification and acceptance boundary.

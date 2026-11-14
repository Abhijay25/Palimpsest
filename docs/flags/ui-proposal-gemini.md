## 1. Design Rationale: Adapting Google Docs Comments

**Kept from Google Docs:**
- **Spatial margin anchoring:** Cards sit in a right margin aligned to the `top` of their target text (`anchor_text`), letting admins connect claim to diff line peripherally.
- **Collision stacking:** Nearby flags push lower cards down with an `8px` (`@spacing-50`) gap so cards never overlap.
- **Active-card shift:** Activating a pushed-down card snaps *that* card flush with its anchor’s exact `Y` coordinate and displaces siblings above and below—preserving spatial truth when reading dense hunks.
- **Bidirectional hover/focus coupling:** Focusing/hovering a card intensifies its diff `<mark>` and extends a connector tick; clicking `<mark>` activates its card.

**Changed for Wikipedia diff auditing:**
- **No reply threads or destructive “Resolve”:** Audits are solo triage, not collaborative chat. Deleting resolved cards hides audit history if misclicked. Instead, a **Reviewed (`✓`)** toggle collapses a card in place to a `28px` single-line pill, reversible in one click.
- **Advisory rewrites only:** Unlike Docs Suggestion Mode, `neutral_rewrite` never mutates wikitext directly. Admins get a **Copy rewrite** button.
- **Single right rail for both sides:** Splitting `old` flags left and `new` flags right forces 1,200px horizontal eye jumps. All cards live in one right rail; `old`-side flags carry an explicit `← OLD` badge and highlight inside `td.diff-deletedline`.

---

## 2. Layout & Responsive Behaviour

Wrap `table.diff` inside `.pf-root` containing sticky `.pf-summary-bar` above `.pf-workspace` (CSS Grid: diff column + `.pf-rail`). Measure `.pf-workspace` width via `ResizeObserver` so Vector 2022 pinned menus (left Main Menu/TOC, right Tools/Appearance) are handled by actual available space, not brittle sidebar selectors.

- **Sticky top offset (`--pf-sticky-top`):** Measured from `.vector-sticky-header` (`50px` when visible, `0px` otherwise). `.pf-summary-bar` uses `position: sticky; top: var(--pf-sticky-top); z-index: 30`.
- **Rail mode (4-column diff):** Active when `window.innerWidth >= 1000px` **and** `.pf-workspace.clientWidth >= 900px`.
  - Grid: `grid-template-columns: minmax(0, 1fr) 288px; column-gap: @spacing-100` (`264px` rail if workspace is `900–999px`).
  - Reserved immediately at `t=0` so diff lines do not reflow horizontally when flags arrive at `2–8s`. Collapses to `1fr 0px` (`column-gap: 0`) if `flags.length === 0` or on API failure.
- **Inline diff mode (`table.diff.mw-diff-inline`):** Single diff column needs less width; Rail mode stays active down to `.pf-workspace.clientWidth >= 760px` (with `window.innerWidth >= 1000px`).
- **Pinned Vector side menus (`1000px+` viewport, `< 900px` workspace):** Switches automatically to **Compact Popover mode**.
- **Compact Popover mode (`720px <= window.innerWidth < 1000px`, or `< 900px` workspace):** `.pf-rail` hides. Each `<mark>` appends an inline focusable badge `<button class="pf-inline-pin">` (`[Icon 1]`). Clicking a pin or pressing `[`/`]` opens `FlagCard` in a `340px`-wide `CdxPopover` anchored to `<mark>` (`placement="bottom-start"`).
- **Mobile (`window.innerWidth < 720px`):** Same inline pins; activating opens `FlagCard` inside a bottom-sheet `CdxDialog` (`max-height: 65vh`), keeping the highlighted diff line visible in the upper `35vh`.

---

## 3. Collapsed Card Anatomy & Colour System

**Collapsed card (`<= 88px` tall):** `@background-color-base`, `1px solid @border-color-subtle`, `@border-radius-base` (`2px`), `4px solid var(--pf-kind-accent)` left border, `@spacing-50` (`8px`) padding.
1. **Header row (`flex`, `gap: @spacing-25`):**
   - **Kind/Tier chip (`CdxInfoChip` + `.pf-chip`):** Unique Codex icon + uppercase label (non-colour type cue). Tier cue: **`admin`** = solid filled chip + bold `Admin` tag; **`review`** = `1px` outlined chip on transparent bg + subtle `Review` tag.
   - **Side pill:** Rendered only if `side === "old"`: mono badge `← OLD`.
   - **Reviewed button (right-aligned):** Quiet icon-only `CdxButton` (`cdxIconCheck`, `aria-pressed`).
2. **Title (`.pf-card__title`):** `flag.title`, `14px` (`@font-size-small`), weight `600`, clamped to **2 lines** (`-webkit-line-clamp: 2`).
3. **Reason preview (`.pf-card__preview`):** `flag.reason`, `12px` (`@font-size-x-small`), `@color-subtle`, **1 line** (`text-overflow: ellipsis`).

**Kind palette & tokens** (Dark mode applied under `html.skin-theme-clientpref-night` and `@media (prefers-color-scheme: dark)` with `html.skin-theme-clientpref-os`; all chip text contrasts `>= 4.8:1` WCAG AA):

| Kind | Icon + Label | Light (`admin` solid bg/fg · `review` border/fg · `<mark>` tint) | Dark (`admin` solid bg/fg · `review` border/fg · `<mark>` tint) |
|---|---|---|---|
| `FACT` | `cdxIconAlert` `FACT` | `@color-destructive` `#b32424`/`#fff` (6.5:1) · `#b32424` · `@background-color-destructive-subtle` | `#fd7865`/`#101418` (7.4:1) · `#fd7865` · `rgba(253,120,101,.24)` |
| `MOTIVE` | `cdxIconUserTalk` `MOTIVE` | `#6b4ba1`/`#fff` (6.3:1) · `#6b4ba1` · `rgba(107,75,161,.16)` | `#bba2e5`/`#101418` (8.6:1) · `#bba2e5` · `rgba(187,162,229,.24)` |
| `FRAMING` | `cdxIconQuotes` `FRAMING` | `#f0b400`/`#101418` (10.3:1) · `@border-color-warning` `#7a4a00` (7.1:1) · `@background-color-warning-subtle` | `#eeb533`/`#101418` (10.2:1) · `#eeb533` · `rgba(238,181,51,.24)` |
| `REMOVED_CONTEXT` | `cdxIconSubtract` `REMOVED` | `#b95000`/`#fff` (4.8:1) · `#b95000` · `rgba(185,80,0,.18)` | `#ff9e5e`/`#101418` (9.3:1) · `#ff9e5e` · `rgba(255,158,94,.24)` |
| `HIDDEN_TEXT` | `cdxIconEyeClosed` `HIDDEN` | `#101418`/`#fff` (18.4:1) + `1.5px solid @color-destructive` · `#f8f9fa`/`#101418` + `1.5px dashed #d73333` · `rgba(16,20,24,.14)` + `1px solid #d73333` | `#080a0c`/`#f8f9fa` (18.8:1) + `1.5px solid #fd7865` · `#202122`/`#eaecf0` + `1.5px dashed #fd7865` · `rgba(0,0,0,.55)` + `1px solid #fd7865` |
| `CITATION_DATE` | `cdxIconClock` `DATE` | `@color-progressive` `#3366cc`/`#fff` (5.3:1) · `#3366cc` · `@background-color-progressive-subtle` | `#88a3e8`/`#101418` (7.9:1) · `#88a3e8` · `rgba(136,163,232,.24)` |
| `CITED_PAGE` | `cdxIconReference` `SOURCE` | `#0e7369`/`#fff` (5.6:1) · `#0e7369` · `rgba(14,115,105,.16)` | `#59d1c5`/`#101418` (10.8:1) · `#59d1c5` · `rgba(89,209,197,.24)` |

---

## 4. Anchoring & Stacking Algorithm

### Anchor Resolution
1. **Cell indexing:** Collect candidate cells for `flag.side`:
   - 4-col `old`: `td.diff-deletedline`, left `td.diff-context`; `new`: `td.diff-addedline`, right `td.diff-context`.
   - Inline diff: `td.mw-diff-inline-deleted` / `-added` / `-changed` / `-context`. When indexing `-changed`, skip `<ins>` subtrees for `old` and `<del>` subtrees for `new` so `anchor_text` matches cleanly across inline edits.
   - Normalize `\u00a0` to `" "` and map cumulative char index `-> (TextNode, offset)`. Record hunk start lines from `td.diff-lineno`.
2. **Pass 1 (Offsets):** Because `table.diff` omits unchanged lines between hunks, raw wikitext offsets apply directly only when a single hunk begins at line 1 (`lineno === 1`) and `[anchor_start, anchor_end]` equals `anchor_text`. Otherwise compute `approxLine = 1 + (anchor_start / 80)` as a tie-breaker.
3. **Pass 2 (Text fallback across `del.diffchange` / `ins.diffchange` / plain text):**
   - Search changed cells first, then context cells, for whitespace-normalized `context_sentence`, then locate `anchor_text` inside it.
   - If `context_sentence` crosses rows/templates, search cells for `anchor_text` directly; break ties by highest 3-gram character overlap with `context_sentence`, then presence inside `<ins class="diffchange">` / `<del class="diffchange">`, then closeness to `approxLine`.
   - For zero-width `HIDDEN_TEXT` where `anchor_text` has `0` rendered width, match `context_sentence`, split at the invisible char, and insert `<span class="pf-zw-badge">[ZW]</span>` inside `<mark>`.
4. **Wrapping:** Split start/end `Text` nodes and wrap each intersecting `Text` node segment in `<mark class="pf-anchor" data-pf-id="{id}">`, preserving existing `<ins>`/`<del>` DOM hierarchy.
5. **Unresolvable anchors:** Render in a collapsible **“Unanchored flags (`N`)”** strip directly below `.pf-summary-bar`, quoting `context_sentence` with `anchor_text` bolded inside the card.

### Vertical Alignment & Collision Resolution
- Compute `idealY = firstMark.getBoundingClientRect().top - rail.getBoundingClientRect().top`.
- Sort anchored flags by `(idealY ASC, markLeft ASC, tier === 'admin' ? 0 : 1, id ASC)`.
- **Default pass:** `y[0] = Math.max(0, idealY[0])`; `y[i] = Math.max(idealY[i], y[i-1] + h[i-1] + 8)`.
- **Active-card shift pass (active index `k`):**
  1. Pin `y[k] = Math.max(0, idealY[k])`.
  2. Sweep up (`i = k-1 .. 0`): `y[i] = Math.min(idealY[i], y[i+1] - h[i] - 8)`. If `y[0] < 0`, add `-y[0]` to `y[0..k]`.
  3. Sweep down (`i = k+1 .. n-1`): `y[i] = Math.max(idealY[i], y[i-1] + h[i-1] + 8)`.
- Set `.pf-rail` `min-height: ${y[n-1] + h[n-1]}px`; apply `transform: translateY(${y[i]}px)`.
- **Re-layout triggers:** `ResizeObserver` on `table.diff` and `.pf-workspace`, `document.fonts.ready`, card expand/collapse/review, and `mw.hook('wikipage.diff')` (handles live 2-column/inline switching).

---

## 5. Interactions, Summary, Minimap & Expanded View

- **Expanded view — Inline margin expansion** (Rail mode): Chosen over popovers because a popover covers diff text or neighbouring margin cards, whereas inline expansion keeps both diff columns 100% unobstructed while shifting sibling cards smoothly. Only one card expands at a time (`activeFlagId`).
- **Expanded card content order (`FlagCard.vue`):**
  1. Header: Kind/Tier chip, `← OLD` pill (if `old`), **Confidence badge** (`High 85%` `>=0.8`, `Medium` `0.5–0.79`, `Low` `<0.5`), Reviewed `✓` button.
  2. Unclamped `title`.
  3. Full `reason`.
  4. `evidence` list: compact `<blockquote class="pf-evidence">` per item with source tag (`Cited source` linked to `url`, `Old text`, `New text`) + `"quote"`.
  5. `citations`: deduplicated external domain links (`target="_blank" rel="noopener noreferrer"`).
  6. `neutral_rewrite` (if non-null): `@background-color-neutral-subtle` box + quiet `CdxButton` `Copy rewrite` (`Copied` feedback for `1.5s`).
  7. Footer: `Check: {check}` label + `Jump to text` / `Mark reviewed` quiet action.
- **Pointer & keyboard:**
  - **Hover / Focus:** Adds `.pf-anchor--active` (`2px` solid bottom border + doubled tint) and draws a `12px` left connector tick on the card.
  - **Click / `Enter` / `Space`:** Expands card (or opens popover/dialog in Compact mode), runs active-card shift, scrolls `<mark>` into viewport if outside `[stickyTop + 60px, innerHeight - 80px]` (`scroll-margin-top: calc(var(--pf-sticky-top) + 64px)`).
  - **`Escape`:** Collapses active card and returns focus to its collapsed toggle button (or `.pf-inline-pin`).
  - **Shortcuts** (ignored inside `input, textarea, select, [contenteditable]` or with `Ctrl/Alt/Meta`—no clash with MediaWiki `Alt+Shift+*` accesskeys): `]` or `j` = next unreviewed flag; `[` or `k` = previous unreviewed flag; `x` = toggle Reviewed and advance.
- **Summary bar & scrollbar minimap:**
  - `.pf-summary-bar`: Shows tier counts (`2 Admin`, `1 Review`), clickable kind filter chips, `1 / 3` counter with Prev `[` / Next `]` `CdxButton`s, and `Show reviewed` toggle.
  - `.pf-minimap`: `6px`-wide fixed right-edge track (`inset-inline-end: 0; top: var(--pf-sticky-top); bottom: 0`) rendering clickable colour-coded ticks at `(markDocY / docHeight) * 100%` for instant navigation on long diffs.

---

## 6. States

- **Loading (`2–8s`):** Diff renders at `t=0`. `.pf-summary-bar` renders inline `CdxProgressIndicator` + `"Checking this edit…"` (`"Still checking cited sources…"` at `5s`).
- **No flags:** `.pf-summary-bar` displays `CdxInfoChip` (`status="success"`) `"No issues flagged"`; `.pf-rail` collapses to `0px`.
- **API error / timeout (`12s` `AbortController`):** `CdxInfoChip` (`status="warning"`) `"Audit unavailable"` + `Retry` `CdxButton`; `.pf-rail` collapses.
- **Partial result (`response.partial === true`):** Render returned flags; append warning chip `"Partial check (some sources timed out)"` + `Retry` in `.pf-summary-bar`.
- **Stale cache:** Discard responses whose `(oldRevId, newRevId)` mismatch `mw.config.get('wgDiffOldId' / 'wgDiffNewId')`. If `response.stale === true`, show `"Cached result · Re-check"` quiet `CdxButton`.

---

## 7. Accessibility

- **Semantics:** `<aside class="pf-summary-bar">` and `<aside class="pf-rail" aria-label="Palimpsest flags">` containing `<ol class="pf-rail__list">`. Card header toggle uses `<button aria-expanded="true|false" aria-controls="pf-body-{id}">`.
- **Bidirectional link:** `<mark id="pf-mark-{id}" aria-details="pf-card-{id}">`; expanded card includes `"Jump to highlighted text"` button moving focus/scroll to the diff cell; Compact pins use `aria-label="Flag 1, Admin Fact: {title}"`.
- **Live region:** Single `<div class="pf-sr-live" role="status" aria-live="polite" aria-atomic="true">` announces once on completion: `"Palimpsest found 2 admin flags and 1 review flag. Press right bracket for next flag."`
- **Motion & focus:** `@media (prefers-reduced-motion: reduce)` sets card `transform` transitions to `0ms` and `scrollBehavior: 'auto'`. `CdxDialog` manages focus trapping on mobile; `Escape` always restores trigger focus.

---

## 8. Module Breakdown & DOM Structure

**ResourceLoader module `ext.palimpsest.diff`:**
- `init.js` — Hooks `mw.hook('wikipage.diff')`, mounts `.pf-root` around `table.diff`, manages `AbortController`.
- `api.js` — `fetchDiffAudit(oldId, newId, signal)` with `12s` timeout and revision validation.
- `anchoring.js` — Cell text indexer, inline-diff `<ins>`/`<del>` filter, 3-pass matcher, `<mark>` wrapper/unwrapper.
- `stacking.js` — `computePositions(items, activeId)` + `ResizeObserver` / font-load scheduler.
- `components/DiffAuditApp.vue` — Root state (`status`, `flags`, `activeId`, `reviewedIds`, `layoutMode`), shortcuts, `CdxPopover` / `CdxDialog` hosts, minimap.
- `components/SummaryBar.vue` — Sticky bar (`CdxProgressIndicator`, `CdxInfoChip`, `CdxButton`) + unanchored tray.
- `components/FlagCard.vue` — **Diff-agnostic reusable card** (`props: { flag, expanded, reviewed, standalone }`), ready to drop into the future Issues page.
- `styles/palimpsest.less` — Grid, Codex token mappings, dark-mode mixins, `<mark>` and minimap styles.

```html
<div class="pf-root" data-pf-mode="rail">
  <aside class="pf-summary-bar" aria-label="Palimpsest audit summary">…</aside>
  <div class="pf-unanchored-tray" hidden>…</div>
  <div class="pf-workspace">
    <table class="diff">
      <tr>
        <td class="diff-addedline">
          <div>…<ins class="diffchange"><mark class="pf-anchor pf-anchor--fact" id="pf-mark-u0-s1" data-pf-id="u0-s1" aria-details="pf-card-u0-s1">1,200</mark></ins>…</div>
        </td>
      </tr>
    </table>
    <aside class="pf-rail" aria-label="Palimpsest flags">
      <ol class="pf-rail__list">
        <li class="pf-rail__item" style="transform: translateY(142px)">
          <article id="pf-card-u0-s1" class="pf-card pf-card--fact pf-card--admin pf-card--expanded">
            <button class="pf-card__toggle" aria-expanded="true" aria-controls="pf-body-u0-s1">…</button>
            <div id="pf-body-u0-s1" class="pf-card__body">…</div>
          </article>
        </li>
      </ol>
    </aside>
  </div>
  <div class="pf-minimap" aria-hidden="true"><button class="pf-minimap__tick" tabindex="-1"></button></div>
  <div class="pf-sr-live" role="status" aria-live="polite"></div>
</div>
```

---

## 9. Browser-Testable Acceptance Checks

1. **Non-blocking render:** With API delayed `5,000ms`, `table.diff` is visible `< 100ms` after load with `.pf-summary-bar` showing `CdxProgressIndicator` and zero horizontal shift when flags resolve.
2. **Span wrapping across diff tags:** A `new`-side flag whose `anchor_text` spans `<ins class="diffchange">` and plain text wraps both segments in `mark.pf-anchor[data-pf-id]` without altering `table.diff.textContent`.
3. **Inline diff disambiguation:** On `table.diff.mw-diff-inline` containing `<del>900</del><ins>1,200</ins>`, an `old` flag highlights only `900` and a `new` flag highlights only `1,200`.
4. **Collision & active shift:** Three flags on the same `<tr>` stack with consecutive `cardRect[i].top - cardRect[i-1].bottom >= 8px`; clicking the 3rd card sets `Math.abs(cardRect[2].top - markRect[2].top) <= 1px` and shifts cards 1–2 upward without overlap.
5. **Keyboard workflow:** Pressing `]` activates flag 1 and scrolls `#pf-mark-u0-s1` into view; pressing `x` marks it reviewed (`aria-pressed="true"`, height `<= 32px`) and activates flag 2; `Escape` collapses flag 2 and focuses its `.pf-card__toggle`.
6. **Responsive & pinned menus:** Resizing viewport to `900px` (or shrinking `.pf-workspace` `< 900px` via pinned Vector sidebars) hides `.pf-rail`, renders `.pf-inline-pin`, and opens `FlagCard` in `.cdx-popover` (`>= 720px`) or `.cdx-dialog` (`< 720px`).
7. **Dark mode contrast:** Toggling `html.skin-theme-clientpref-night` yields computed contrast `>= 4.5:1` on all 7 kind chips for both `admin` and `review` tiers.
8. **Unresolvable fallback:** A flag with `anchor_text: "NONEXISTENT"` renders inside `.pf-unanchored-tray` with `context_sentence` visible and zero console errors.
# Diff flags in the wiki UI (PalimpsestFlags)

## Intent

Admins review edits on the wiki's revision diff page. Diffs can be long, so finding the
problem must not require reading the whole diff. Each possible issue appears as a note in a
margin beside the diff, like a comment in a Google Doc. Hovering a note highlights the exact
text in the diff it refers to; clicking it opens a popup with the full reason, confidence,
evidence and citations. The admin decides; the note only says why the change deserves a look.
An Issues page (like GitHub issues) will reuse the same flag records later; it is out of
scope here, but the flag record format below is designed so it can be listed there.

## Pieces

1. **Palimpsest API (Python, this repo).** `POST /api/v1/audit-diff` already returns the
   verdict, units, flagged spans, stealth, render and citation-date results. Add a
   `flags` list (contract below) so the UI does not have to interpret the rest.
2. **MediaWiki extension `infra/wiki/extensions/PalimpsestFlags`** (PHP + JS), following the
   conventions of `PalimpsestBlame` (extension.json, ServiceWiring, i18n, ResourceLoader
   module, tests in the pinned containers).
   - PHP: on diff views (`DifferenceEngineViewHeader` or equivalent hook) load the module with
     page title, content language, old and new revision IDs. An Action API module
     `action=palimpsestflags&oldid=&diff=` loads both revisions' wikitext server-side
     (RevisionLookup), calls the Palimpsest API (`$wgPalimpsestFlagsApiUrl`, timeout
     `$wgPalimpsestFlagsTimeout`), and caches the response per (old rev, new rev,
     `api_version`) in the main object cache. Never sends user data beyond the two revisions,
     title, language and revision IDs. Errors become a visible, non-blocking notice.
   - JS: renders a right-hand gutter beside the diff table with one note per flag, vertically
     aligned with the diff row that holds its anchor text (stacked without overlap when
     several anchor to nearby rows). The note shows a coloured type chip and the reason,
     truncated to two lines. Hover or keyboard focus highlights the anchor text inside the
     diff cell (wrap the matched text range; scroll it into view if off-screen). Click or
     Enter opens a popup: full reason, type, severity, confidence, the sentence in context,
     evidence quotes, cited URLs (links), suggested neutral rewrite, and which check produced
     it. While the audit runs (several seconds), show a "Checking this edit" placeholder; the
     diff itself is never delayed.
3. **Running together.** The API runs as a separate process (`uvicorn palimpsest.api:app`);
   the wiki reaches it through `$wgPalimpsestFlagsApiUrl` (compose override with
   `extra_hosts: host.docker.internal:host-gateway` for a host-run API). No change to the
   teammates' base compose file.

## Flag contract (`flags` in the audit-diff response)

```json
{
  "id": "u0-s1",                       // stable within one response
  "kind": "FACT | FRAMING | MOTIVE | REMOVED_CONTEXT | HIDDEN_TEXT | CITATION_DATE | CITED_PAGE",
  "tier": "admin | review",            // severity: admin = strong evidence, review = worth a look
  "title": "Number changed from 900 to 1,200",   // <= 80 chars, plain language
  "reason": "The cited source gives 900; the edit replaces it with 1,200.",
  "confidence": 0.85,
  "side": "new | old",                 // which side of the diff holds the anchor
  "anchor_text": "1,200",              // exact text to highlight
  "anchor_start": 512, "anchor_end": 517,        // offsets into that side's submitted wikitext, or null
  "context_sentence": "…sentence containing the anchor…",
  "evidence": [{"source": "cited | old | new", "quote": "…", "url": "https://…"}],
  "citations": ["https://…"],
  "neutral_rewrite": "…" ,             // or null
  "check": "judge | stealth | citation_dates | render"
}
```

- Every judge `flagged_span`, every stealth finding, every citation-date finding and every
  escalating render finding becomes one flag. `REMOVED_CONTEXT` anchors on the old side.
- Offsets are into the wikitext that was submitted for that side; the UI falls back to text
  search when they are null or do not match the rendered diff cell.
- Colours by kind (fixed, accessible in light and dark): FACT red, MOTIVE purple, FRAMING
  amber, REMOVED_CONTEXT orange, HIDDEN_TEXT near-black with a red outline, CITATION_DATE
  blue, CITED_PAGE teal. Tier `admin` = solid chip, `review` = outlined chip.

## Cost and latency

One audit per (old, new) revision pair, cached; repeat views are instant. The audit runs only
when a diff page is opened (and only when the API is configured), so Gemini is not called for
pages nobody reviews. Stage-0-clean diffs return no flags without a model call.

## Verification

Python: contract tests for `flags` (one per kind, both sides, offsets). Extension: PHP tests
for the API module (mocked HTTP, caching, error path) and JS tests in the pinned browser
image with a mocked API response: notes render beside the right rows, hover highlights the
right text on each side, popup content, truncation, stacking, keyboard access, light/dark.
Then one live check on the local wiki with a real edit and the real API.

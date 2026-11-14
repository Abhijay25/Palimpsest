# p02 — Pillar 3 render audit (2026-11-14 14:50–15:00)

Render: system Chromium via Playwright (no browser download), viewport 1280x800, tiles top to bottom with 64 px overlap, max 12 tiles. Deterministic visibility model (display/visibility/opacity/contrast/font size/off-screen/clip/zero size/occlusion via elementFromPoint, ignoring fixed/sticky UI), then Haiku triage of hidden text, then (separately) Haiku vision on image-bearing tiles.

## Deterministic + Haiku triage
| Set | Result |
|---|---|
| 16 blind ATTACK pages (Sonnet-written, never saw the code; 15 techniques, 5 languages) | planted text recovered 16/16, **flagged 16/16** |
| 10 blind BENIGN pages with legit hidden UI (skip links, mobile menu, accordions, cookie banner, sticky header) | findings on 6, **flagged 0/10** |
| 37 real cited pages (live render; 3 timeouts) | findings on 16, **flagged 1/37** — a magazine paywall overlay covering article text (true occlusion, not poisoning) |
| p50 render time per page | 1.1 s (simple pages ~0.4 s, heavy news pages 8–20 s) |

Dev-set fixes made on this run (so these 37 URLs are now a dev set; re-measure on a fresh sample):
- Compare judged (Exa) text against the DOM before calling it hidden: Exa's earlier fetch vs today's page differ for PDFs, paywalls and edits (first attempt produced 10,291 "scraper-only" findings on 40 pages). Drift is now reported separately (`judged_drift`).
- Skip hidden nodes whose text is also visible (responsive duplicates of headlines/menus).
- Scroll-locked pages (consent dialogs) produced identical tiles; tiles are now captured from the full-page layout when the page refuses to scroll.

## Vision layer (Haiku stand-in for Hydrogen), 30 tiles
- IMAGE_TEXT attacks (text drawn only inside an SVG image, en/de/fr): **4/4 caught**, verbatim.
- Real pages: **4/8 flagged** — a scanned Google Books page, a faded paywall paragraph, a streaming banner, a newsletter ad. As a standalone escalator this is far too noisy.
- Decision: vision findings do not escalate on their own. Next step is a claim-relevance gate (image text must relate to the cited claim) and running vision only on high-risk cases, which also caps image-token cost.

Pages that 403/robot-wall or fail to render are reported as `unavailable`, never as clean.

# Native Issues delivery audit

The implementation and selected native-runtime verification are delivered on
`feature/unified-article-preview`. This is not user acceptance of complete native
parity. Both previews remain running. Nothing from the separate NeoWikiReview
experiment was merged, and upstream MediaWiki remains digest-pinned.

The [setup and detailed verification record](native-issues.md) provides commands,
exact source/local revisions, rendering pins and the distinction between real
cached results, synthetic UI tests and fresh inference.

| Requirement | Implemented behavior and evidence | Boundary |
| --- | --- | --- |
| Native Article / Issues | Native article action and action API; Issues list/evidence render inside MediaWiki. Core renders the complete imported article, without an iframe. Real FI/SV/EN browser/API checks. | Imports are selected revisions, not full article histories. |
| Real templates, references and media | Official pinned Wikibase, CLDR, Labeled Section Transclusion and GeoData; actual bounded source dependencies and 143 reconciled entities per wiki. Five exact article renders compared with source parser captures. Winter War section/reference/image counts match; FI/SV text matches and EN differs only in romanization-label spacing. Mänttä FI/SV normalized text matches. Browser images load; actual mobile article widths checked. | Source template/media dependencies can reflect acquisition time. No historical template-environment reconstruction or whole-corpus visual certification. |
| Exact source identity | Verified provenance bundles bind title/page, edition, source/local revision/parent, timestamps, readability and body SHA. Real historical links and selector changes resolve to correct core oldid. Missing/deleted/tampered/unmapped selections fail explicitly. PHP tests and real API/browser checks. | Unimported source revisions stay unavailable. Source IDs are never guessed as local IDs. |
| Explicit selected scans | Selected revision/page controls, native scan right and CSRF; no native bulk loop. Reads reuse archived successes and do not infer. Fresh requests are explicit. Source text hash and edit-parent reconciliation checked before scanning. | Acceptance made no fresh paid requests; live detector accuracy is not certified. |
| Cache, readiness and failures | Real three-flag revision cache and successful-empty page result. Controlled private detector outage preserved both; Retry restored readiness. Archived successes survive loss of working caches. Native saved-page reads skip the redundant preview/source HTML renderer and use only native parser output. Unit/database cases distinguish failed/partial/running/empty states and preserve successes. | The local installed detector remains an external service dependency for new scans. |
| Flags interactions | Shared word diff, anchoring, severity/type filters, next/previous, collision handling, unanchored tray and mobile anchored popovers. Shared asset equality checked. Real cached desktop/mobile comment journeys verified. | Real cached findings represent suggestions, not confirmed errors. |
| Positive page annotations | Temporary read-only signed UI fixture used the real native parsed article. Visible explanations, actual quote highlight, keyboard activation and explicit absent-anchor feedback verified on desktop/mobile. Normal real empty cache restored afterward. | Clearly synthetic annotations were never persisted or described as detector output. No real cached positive page-consistency sample exists. |
| Immutable evidence and clocks | Original observations/assessments stay separate from derived metadata and review markers. Source edit, observation checkpoint, assessment and database system time retain separate labels. Unknown snapshot dates remain unknown. Immutable-rescan and SVT tests passed; original assessment and provider-ledger checks recorded. | Missing observations do not establish resolution, persistence or current article status. |
| Latest, history and coverage | Latest assessed sets retain the latest original language run/checkpoint plus newest successful detector set per scope. History does not union all old runs into latest. Real latest list: 135 language findings plus three flags. Native period lists label observation counts separately from histogram unions. | Sparse assessments are not continuous monitoring or complete coverage. |
| Native review / undo | Native account ID, wiki/observation/edition scope, separate review right, POST/CSRF and SVT. Real admin review/undo restored unreviewed; EN changes did not affect FI. Ordinary account may review but not scan. Anonymous mutation requests rejected. Isolated DB history/undo tests passed. | Preview markers remain separate; a review marker does not confirm, dismiss or resolve a finding. |
| All histogram classifications | Nine uppercase detector types plus three lowercase language categories have separate names, colors and filters. Source-time detector buckets preserve assessment time separately. Sparse coverage and undated findings are explicit. Python/Node checks passed. | Detector `FRAMING` and language `framing` remain distinct even under database collations. |
| Existing histogram behavior | Monthly minimum, original period unions, pair selection, zoom and browser-return state preserved. Native month handoff retains run, editions, dates and selected kinds. Actual browser round trip verified. | Native history counts observations; it does not falsely claim to equal union-of-issue bucket counts. |
| Exact historical finding handoff | Native links retain issue/observation, original run/group/checkpoint and exact occurrence. A weaker coverage occurrence round trip retained its classification despite stronger framing evidence in the same group/pair/checkpoint. | Missing or mismatched identities fail; no strongest-occurrence substitution. |
| No inference while browsing | Native/list/history/histogram/source reads do not scan or backfill. Opening uncached translations now waits for the explicit button; cached translations are read-only. Tests and unchanged provider-ledger count support this. | Explicit local translation/search computation and explicit paid scans retain their existing separate controls. |
| Existing work and runnable previews | Owned native runtime only: FI 18091, SV 18092, EN 18093. Preview ports 8025 and 8026 preserved. Startup disk guard retained. Private secrets, captures, reports and runtime files remain ignored. | Keep both previews until the user explicitly verifies complete native content and interaction parity. |

No Wikipedia edits or paid acceptance scans were part of this verification.
Source changes are published for review separately; no merge is performed by this task.
The later [Wikipedia-defaults update](wikipedia-defaults.md) removes the legacy
Blame tab while retaining the deliberate Issues workflow. Remaining acceptance concerns are complete user visual and
interaction acceptance, generalization beyond these selected article revisions,
and fresh detector execution/accuracy if separately desired. The source import
helpers report incomplete static closure and retain resumable throttled downloads;
they do not conceal missing dependencies or substitute current article bodies.

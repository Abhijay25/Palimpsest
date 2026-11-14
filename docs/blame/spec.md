# Real Blame specification

Approved implementation: execute IMPLEMENTER_PROMPT.md F01–F08 and G1–G7. The human explicitly requested a fork and continued implementation; routine recommended decisions are preapproved. This specification freezes those requirements without repeating the infrastructure approval gate.

Deliver an idiomatic MediaWiki extension, PalimpsestBlame, on the actual Vector2022 wiki. Word/phrase attribution and cross-contributor selections open an inline history beneath the selected statement on desktop/mobile. Deleted/replaced wording belongs in that timeline. Snapshot/date/blame IDs always agree. Editor attribution is separate from truth/evidence and inferred intent. No fictional metadata or attribution, external LLM or messaging.

Scope: actual public local wikitext revisions, with verified source/local provenance for imported sample pages and ordinary local edits. Unsupported/generated source regions must remain unannotated and explicitly unavailable. Missing/hidden history or stale mappings cannot produce authoritative attribution. Preserve all existing wiki workflows. Full S seeding is a separate parent infrastructure job; neither this feature nor its sample checks certify that corpus.

F01 action/snapshot/errors → T1/T2/T4; F02 last-change/ambiguity → T1/T4; F03 exact selection/inline/mobile/keyboard → T2/T4; F04 metadata/links/evidence/privacy → T1/T2/T4; F05 deleted/replaced lineage/diffs → T1/T2/T4; F06 deterministic date navigation → T1/T2/T4; F07 source/local mappings/local edits → T1/T3/T4; F08 bounds/cache/jobs/permissions/reproducibility → T1/T3/T4. Full definitions remain in IMPLEMENTER_PROMPT.md.

Acceptance: independently expected synthetic histories, actual fi/sv/en sample histories, local-edit invalidation, corrupt/missing mapping negatives, UTC/date boundary negatives, desktop/mobile/keyboard browser use, existing wiki regression/restart, bounded cache/job recovery and measured timings. No whole-site feature parity, exact historical rendering, unique original authorship proof or native-mobile-device coverage is implied.

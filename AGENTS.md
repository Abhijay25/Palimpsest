# NeoWiki agent context

Read [the exploration registry](docs/explorations/README.md) before extending a prototype. It records the independent experiments, their source locations, what is actually shipped here, data provenance, validation and unfinished work. Update the registry when adding, retiring or combining an exploration; do not overwrite one experiment's data/status with another's.

## Repository and PR boundaries

- The main branch owns the Finnish/Swedish/English MediaWiki infrastructure and its existing source/local revision reconciliation contracts.
- PR #4 (`feature/divergence-visualization`) adds the independent optional tool under `tools/divergence-explorer`. It does not install a native extension or include the historical inference worker.
- The follow-up `feature/interlanguage-comparisons` branch directly copies the existing working app into `tools/language-gap-explorer`, with source hashes and no implementation rewrite. It is based on PR #4. Keep the PR stacked against `feature/divergence-visualization` while #4 remains open; retarget after it merges.
- The separate `feature/neowiki-review-tools` implementation is an unpublished native extension/worker experiment. Do not silently include its unverified import/recovery work in the standalone tool PRs, modify upstream MediaWiki core, or conflate source revision timestamps with system-versioning processing timestamps.

## Product and evidence rules

Current iteration: `feature/divergence-skyline` changes only the existing research app's `/explore` presentation and historical tracker handoff. It uses EN/FI/SV Winter War data: 324 distinct questions across 26 observations, 3,535 source occurrences and 40 source revisions, through July 29, 2025. Latest observation: 128 questions (116 coverage, 12 framing, zero strict contradictions). Do not confuse this cohort with the older EN/FI/RU standalone sample below. The independent `tools/divergence-explorer` implementation is preserved.

`NEOWIKI_RESEARCH_ROOT` optionally points the research code at an existing ignored data/model/environment root; source/templates still come from this repository. The working skyline preview uses port 8022. No native wiki stack changes are part of this iteration.

The current article edition is always on the left/first, with other editions on the right. Preserve explicit language pair/triplet selection, exact source quotes, revision attribution, cached translations, uncertainty and accessible controls. Missing current-edition evidence requires an honest placeholder.

One historical divergence row represents one provisional underlying semantic disagreement/question, with repeated passages/language pairs attached as occurrences. No fixed topic count, English introduction seeds or assumption of shared article structure. Coverage is passage-level additional information; a retrieval miss is not a whole-article omission. Missing observations are not resolution. Sampled annual spans do not establish persistence. Model probabilities are not truth or a calibrated divergence score.

The real Winter War sample contains 520 provisional tracks / 5,005 occurrences / 26 checkpoints, through July 16, 2025. It found coverage/framing differences, with no pairs passing the strict contradiction gate. Tornedalians snapshot findings have unknown lifetimes. Never replace these conclusions with fabricated examples or describe them as current Wikipedia.

## Runtime, secrets and verification

The packaged viewer defaults to database-free operation. The existing research app explicitly requires its research database/dependencies; use its scoped AGENTS.md and PORT.md. Keep read paths free of preparation/model calls. Any optional inference/enrichment must be explicit, cached, metered and subject to the configured engine policy; preserve failed reservations. Never publish Wikipedia edits, secrets, environment files, local paths or private spending ledgers. Exported Wikipedia excerpts retain CC BY-SA attribution and revision links.

Follow `tools/divergence-explorer/AGENTS.md` for tool-specific checks. Use the existing bounded desktop/mobile verification workflow for UI work. Distinguish fixtures, cached real outputs, live engine reads and a fresh end-to-end pipeline run. Do not restart/rebuild the native wiki stack or weaken its disk guards to test the standalone tool.

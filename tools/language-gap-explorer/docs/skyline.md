# Divergence skyline and historical tracker

The research app now provides one complete flow at `/explore`: choose Winter War and EN/FI/SV editions, select a calendar column, then choose a question to open its exact evidence in `/langcompare/Q134949`. The existing article shell, source-first comparison layout, source links, cached highlights, local translations and browser-local review markers are reused.

Run from this directory with the existing research database and dependencies:

```sh
# Optional: point to an existing ignored data/model/environment root.
# Set NEOWIKI_RESEARCH_ROOT using your shell's environment syntax.
python -m flask --app app run --host 127.0.0.1 --port 8022
```

Preparation remains explicit and separate from browsing:

```sh
python -B paired_history.py --languages en,fi,sv --since 2020-01-01 --workers 6
```

This command uses the existing cached revision acquisition, full eligible-prose chunking, MariaDB nearest neighbours, parallel Decisions assessments and provisional grouping. It can download missing public revision samples and make metered classification calls. Page reads never launch it. Reuse the existing research root/model cache rather than initializing another database for a UI iteration.

## Counting and navigation contract

- `GET /explore/api/skyline` returns lightweight observation counts. Each semantic-question ID counts once, using the strongest actual classification among selected language pairs. Raw passage/occurrence counts are not added to column heights. Run configuration plus progress distinguish completed zero-result observations from unobserved checkpoints.
- Calendar bins use the latest completed observation in their period; partial previews are labeled. Values are never summed across observations or carried into missing periods. Zoom chooses calendar years, months, weeks or days to keep approximately 12 desktop/seven mobile columns, with a one-day minimum.
- `GET /explore/api/questions` reads a pinned run/observation, filters by category and returns 10 questions per page. Pagination does not cap discovered topics. Labels use actual selected source sections and existing neutral question types. Source occurrences load from the cache, without inference.
- Tracker links contain the topic, selected editions, run, group, checkpoint and actual occurrence. Category support comes before English preference; FI–SV-only evidence opens with Finnish on the left. The URL shows the destination pair before navigation.
- `/langcompare/<topic>` recognizes historical context before its ordinary snapshot path. It validates the requested source context and shows archived evidence. Missing or mismatched contexts fail explicitly; they never substitute current/snapshot findings. Historical review markers are scoped to the run, group, checkpoint, current edition and selected editions, and remain browser-local.
- The return link and browser history retain the selected observation, category, visible time window and question-list page. The standalone viewer under `tools/divergence-explorer` is unchanged.

## Verified data and limits

The prepared EN/FI/SV sample contains 324 distinct provisional questions across 26 checkpoints and 3,535 source occurrences. It ends at the common July 29, 2025 anchor; the latest observation has 116 coverage and 12 framing questions, with no strict contradictions. The previous 520-question EN/FI/RU sample remains a different dataset.

Every occurrence was audited against normalized source text, source timestamp and its edition's dataset anchor. Sparse annual observations do not establish persistence or resolution, and model grouping is not exhaustive atomic-claim extraction. Historical rendered HTML can contain newer transclusions. Original sources remain authoritative; translations can contain errors. This change does not add live Wikipedia monitoring, bias scores, edit-war detection, automatic editing or a native MediaWiki port.

The old `check_discrepancy_explorer.py` targets the preceding horizontal-track UI. Current skyline validation is `test_skyline.py`, `test_skyline_model.js` and the recorded desktop/mobile in-app browser journey. No new provider requests were made during those UI checks.

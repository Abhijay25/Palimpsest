# Existing comparison and divergence code

This directory brings the **existing working implementation** into Palimpsest. It is not a new comparison engine or reviewer redesign. The Python, templates, styles, JavaScript, setup scripts and existing tests are copied byte-for-byte; `SOURCE_MANIFEST.json` records their exact source hashes, including current working-tree changes.

The original private runtime context is replaced with a curated `AGENTS.md`. Runtime databases, datasets, model weights, environment files, generated reports, private spending data and old screenshots are excluded.

## Existing entry points

| Entry | Purpose |
| --- | --- |
| `app.py` / `start.ps1` | Existing Wikipedia-like article workspace on port 8010. |
| `/langcompare/Q2606233` | Existing Tornedalians inter-language reviewer: language pills, original evidence, highlights, translations and review controls. |
| `/wiki/Q2606233/updates` | Existing chronological local/foreign edit issues and exact diffs. |
| `/watchlist` | Existing confirmed passage relationships and subsequent-change alerts. |
| `/wiki/Q134949/timeline` | Existing Winter War semantic edit-event timeline. |
| `explore_preview.py` / `/explore` | Existing independent temporal divergence explorer on port 8020. |
| `paired_history.py` | Existing symmetric MariaDB nearest-neighbour + parallel Decisions historical comparison engine. |
| `pipeline.py`, `decisions_review.py`, `refine_review.py` | Existing snapshot comparison and focused evidence review pipeline. |

## Use

The unchanged app expects its existing research database and local dependencies. From this directory, use the source README's commands with an environment containing `requirements.lock.txt`. Existing ignored runtime data/caches can be reused in their corresponding locations. `setup.ps1` explicitly acquires the corpus and installs local models for a fresh environment; it is not required to review this PR.

`python app.py` starts the original article/reviewer app; `python explore_preview.py` starts its independent explorer. They are separate from the native three-wiki runtime. Reads do not queue paid comparisons. Any inference/preparation command remains explicit and uses the existing cache/metering policy. Do not start a second database on the same port when reusing the research runtime.

PR #4's standalone viewer remains unchanged in `../divergence-explorer`, with its included real sample and optional `--engine-url http://127.0.0.1:8020` connection. This follow-up supplies the existing source behind that adapter and the existing comparison workspace; it does not require merging the separate native extension branch.

The shared [exploration registry](../../docs/explorations/README.md) records the independent experiments, provenance, superseded approaches and unfinished native work. Model judgments and sparse historical samples retain their original limitations; copying code does not establish a new real-world accuracy result.

# Visualization verification

The PR adds an optional standalone viewer against `main`. It does not include or certify the separate unpublished native NeoWikiReview extension/worker implementation.

## Executed locally

- 15 Python unit/integrity tests passed. They inspect the actual compressed sample as well as isolated edge cases: manifest checksum, group/occurrence references, source revision links and checkpoint cutoffs, language-pair scoping, read-only bundled requests, CSRF, host/input validation, gzip negotiation and the optional engine bridge.
- Both JavaScript files passed `node --check`; Git whitespace checks passed.
- In-app browser verification at `http://127.0.0.1:8021/explore`: blank prompt; real Winter War launch; 520 tracks / 4,449 observed periods; keyboard selection; one track containing four separate bilingual occurrences; exact source text and revision links; current English on the left; bundled enrichment disabled; mobile evidence layout at 390 × 844 with no horizontal page overflow; zoom stops at a one-day interval; reset restores the overview; no captured console errors.
- The dense graph's local JavaScript render measured approximately 109 ms in one browser check. This measures synchronous render work, not total network, layout, ingestion or model processing time.
- The optional engine's read endpoints were checked separately against the prepared local prototype. Forwarded enrichment is covered with mocks; no new provider request was needed for this PR.

## Data provenance and limits

The real prototype backtest completed 26 pinned checkpoints, with 5,005 occurrences and 520 provisional semantic groups. Its source timestamp audit found no evidence newer than its checkpoint; export validates that cutoff again. The committed export has 43 distinct attributed Wikipedia revision URLs, including the cached Tornedalians snapshot sources. It excludes credentials, environment data, local paths and the cost ledger.

The underlying assessment cache contains three failed/unavailable exact pair assessments, retained without automatic provider retries. Counts and gaps are therefore subject to incomplete assessment as well as retrieval and grouping limitations. Completed preparation does not mean every candidate was successfully classified or that model labels are verified. The sample has coverage/framing labels, not a detected contradiction demonstration. Annual sampling does not establish continuous discrepancy lifetimes. Historical rendered HTML can contain newer transclusions.

Default bundled operation made no provider calls. This PR did not build, start, change or revalidate the native three-wiki stack, import canonical wiki content, or exercise a complete historical pipeline from a fresh clone. The ingestion/Decisions worker remains an external integration behind the documented adapter contract.

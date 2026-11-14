# Blame acceptance fixtures

These histories are synthetic ground truth written independently of the Blame
producer. `r1`, `r2`, etc. are fixture aliases, never MediaWiki revision IDs.
The acceptance runner maps them to real local revision IDs when it creates
pages. Fixture authors and provenance are synthetic; they must never appear in
the imported-sample demonstration.

`fixtures/*.json` records complete input histories and explicit expected
attribution, event, selection, ambiguity, date, large-input, and failure outcomes. The
expectations are deliberately declarative so a later producer adapter can check
its output without deriving answers from that producer.

`verify_provenance.py` is read-only. It compares the actual imported sample
against original C3 source records, C4 local mappings, both the operator-trusted
export copy and served configuration copy, then the live API response. The
bundle SHA-256 is a consistency checksum, not a cryptographic signature.

The ordinary CI job validates fixture integrity and runs pure contract checks,
including a 640-token sparse history with expected offsets. The live runner
records the real analyze time and bytes for that history; it does not report a
performance pass until the feature API handles it successfully.

`seed_synthetic.py` creates only synthetic pages and accounts through the core
APIs after an explicit project confirmation. `--include-job-history` adds a
205-revision page for `verify_jobs.py`; neither script changes runtime lifecycle
or touches imported pages. `verify_live.py` checks attribution, date bounds,
token lineage IDs, and cache invalidation. `browser_acceptance.py` checks the
rendered article, selection UI, date navigation, and stale-DOM concurrency in
all languages. It needs explicit browser-reachable origins; it never guesses
Docker Desktop routing.

When validating Python in the pinned container, the fixture mount is
read-only: parse scripts in memory or direct bytecode elsewhere instead of
using `py_compile`'s default in-tree cache path.
The host's Ruby 2.6 YAML parser does not accept the newer `aliases:` keyword;
use its portable `YAML.load_file` call for this workflow syntax check.
That is a structural gate only. Live acceptance is a separate, explicit run
against the feature-only runtime; it must fail when a required capability is
missing and must not turn a backend-unavailable result into a pass. Do not boot,
reset, or seed any shared runtime from this directory's tests. The root
orchestrator owns runtime lifecycle and grants the synthetic page/user scope.

The job test first validates the ordinary fixture's production response, then
prepares the 205-revision target through `op=analyze` and requires
`buildable: true` plus the resolved top-level `revision_id`. It makes a new
latest edit and pins build and status to the earlier revision with the exact
`jobid` parameter. Repeating a pending build request checks that the same
durable job ID progresses to ready. It does not kill/restart the queue worker;
runtime restart/resume and isolated suppressed-content or mapping-corruption
tests stay with the orchestrator's coordinated test copy.

The rendered-link fixture covers a citation anchor and a relative link to a
real synthetic article while Blame is open. The browser check follows both,
then follows a core revision-diff link, to catch action-page base-path changes.

The orchestrator's disposable-copy integrity pass should cover three producer
controls before any sample claim: (1) remove an imported C4 revision record and
expect `imported-revision-provenance-record-missing`; (2) change a local mapped
revision hash/parent and re-canonicalize the bundle, then expect
`provenance-record-does-not-match-local-revision`; (3) alter a bundle without
updating its checksum and expect `provenance-bundle-checksum-mismatch`. Confirm
the untouched sample pages still return ready responses. These controls belong
on the copy because they change trusted provenance inputs.

For cached-job privacy, build and warm a ready job in that copy, then suppress
revision text, identity, and comment separately. Recheck status/analyze with
the same pinned revision: hidden text must make cached history unavailable;
hidden identity/comment must be null, with no value retained from the warm
response. Check that no response includes cached source text or hidden metadata.

The browser runner uses a real mouse drag for the partial-word round and touch
emulation for selection retention after Inspect. Programmatic ranges elsewhere
are followed by the visible Inspect button. It does not claim a physical iOS or
Android gesture; record that separately if device validation is required.

Native mobile text selection is not covered by desktop Chromium emulation. The
browser suite can exercise touch-sized layouts and the deliberate inspect action,
but a real iOS/Android selection gesture requires a separately recorded device
run.

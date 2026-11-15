# Native on-demand assessment jobs

The native Issues **Check for new issues** screen now previews and enqueues edit
scans, page consistency checks and a selected historical language snapshot
comparison. The preview shows the exact source revisions/times/hashes, provider,
models, prompt/policy versions and applicable server allowance. Enqueueing is a
second explicit action. Navigating, filtering, polling and opening evidence never
prepare sources or call a provider. This does not enqueue a bulk history backfill.

## Authentication and ownership

`jobplan` and `enqueue` require a registered native account with
`palimpsest-scan`, write permission, POST and MediaWiki CSRF. Native source and
parent reconciliation uses the existing `SourceMap`; source IDs never become
local revision IDs. PHP supplies the verified account and source hashes over the
private HMAC bridge. Browsers receive no provider key, bridge secret, source file
path, raw provider packet or spending ledger. Public preview routes gain no job
trigger. Legacy synchronous scans are rejected when the queue is configured.

`jobpolicy`, `jobs` and `job` are read-only native operations under article read
permission. Jobs are scoped to native wiki/article; requester account IDs are
retained privately. The queue has no public HTTP listener of its own. The bridge
retains its existing private network and 60-second signed-request window.

The durable SQLite WAL queue and raw provider attempt archive live on an owned
local persistent volume identified by `NEOWIKI_ON_DEMAND_ROOT`. This is separate
from campaign ledgers and the original article preparation queue. It must be
mounted into the bridge and its one worker, never into the public Flask reader.
Network filesystems are not supported. Shared research data/model mounts stay
read-only in the bridge. Missing source texts are acquired on explicit preview
POSTs into the separate owned source cache, with no inference.

## Explicit setup

1. Set the owned root and `NEOWIKI_ON_DEMAND_POLICY` to a private server JSON file.
2. Run `python on_demand_worker.py init` once. This creates only the owned queue.
   Existing unified Issues schema must already have been initialized explicitly.
3. Start `python on_demand_worker.py work` under a process supervisor, from
   `tools/language-gap-explorer`, with the repository on `PYTHONPATH`.
4. Give the worker only its applicable provider credentials via private secret
   mounts/environment. It requires the existing research dependencies, cached
   FastEmbed multilingual E5 model and detector dependencies. It never downloads
   models. The bridge and public reader do not receive provider credentials.

The worker holds one exclusive process lock and starts one child per job. This
isolates provider/model environment and execution namespaces from every other
worker. Disk preparation/processing stops below **30,000,000,000 free bytes**,
preserving the **25 GB minimum**. No Docker pruning, campaign pause/resume,
reservation reset or database replacement is part of setup.

Default policy (safe to deploy without any new paid authorization):

```json
{
  "version": 1,
  "policy_version": "on-demand-disabled-v1",
  "enabled": false,
  "authorization": "No on-demand spending has been approved.",
  "engines": {}
}
```

Enabling an engine requires a separate human-approved authorization record,
article allowlist and positive `max_provider_calls`. The budget is an explicit
**provider-call limit, not a dollar price estimate**. Every actual call, including
failed or uncertain calls, permanently consumes a slot in that authorization.
The UI shows this limit. Changing authorization does not turn a failed job into
a retry. No unattended topic wildcard or inherited historical-campaign allowance
exists. To enforce a dollar ceiling additionally, use the existing configured
OpenAI ledger limit; this code never raises or resets it.

Each engine (`revision`, `page`, `language`) has:

* `enabled`, `topics: ["Q…"]`, `authorization`, `max_provider_calls`, and optional
  `allow_rescan`.
* A credential-free `configuration` with `provider`, `model`, `prompt_version`,
  `policy_version`. Detector configuration also requires `reviewer_model`,
  `triage_model` and bounded `max_output_tokens`.
* Detectors use Gemini; language assessment uses the existing OpenAI Decisions
  pipeline. Versions/models must match the deployed implementation. The currently
  implemented detector prompt is `stage2_v10`; language prompt policy is
  `symmetric-disagreements-v1`. These are implementation identifiers, not fresh
  accuracy claims. Actual model names come from the reviewed private policy.

The full immutable policy hash is checked at enqueue, before execution and before
every provider attempt. Revoking/changing it blocks new calls in existing jobs.
Successful saved-result indexing remains possible after revocation. Secrets in
public engine configuration are rejected rather than returned to the browser.

## Identity, caches and retained evidence

Plans expire after 30 minutes and can be prepared again. They freeze source and
parent IDs/text hashes and full source texts. Language counterparts are chosen
as-of the native selected source timestamp, bounded by their actual dataset
anchors; missing counterparts fail, with no latest-snapshot substitution.

Job/cache identity includes all frozen sources, parent/text hashes where used,
engine/model/prompt/policy configuration and a hash of the deployed detector and
comparison implementation. Concurrent duplicate enqueues have one transactionally
unique job. A repeat POST returns that exact job, including a previous failed or
partial state. Compatible complete successful results are reused. Unversioned
legacy results remain readable but are not asserted to be compatible.

An explicit **Preview fresh rescan** is available only after a complete successful
job and only when server policy allows it. The parent successful job is retained;
the new generation has a separate identity. Repeating the same rescan enqueue
returns the same generation. Failed/partial/unknown generations prevent a further
duplicate. They require operator reconciliation, not a browser retry button.
There is deliberately no command that resets failed paid reservations.

Raw successful provider responses, original request material and usage metadata
remain in private `attempt` rows; source texts/configuration and complete pipeline
results remain in the owned queue/result archive. Safe failure types remain with
retained reservations. Detector evidence is transactionally indexed in existing
`unified_*` tables. Language snapshots retain their exact `paired_run` and
occurrences and are indexed through the existing adapter. Source edit time,
snapshot observation time and assessment time remain distinct.

## Status and recovery

`queued` → `running` → `completed` or `partial`. A complete zero-finding result is
explicitly successful. Missing, failed, partial and unassessed work never becomes
zero. Progress and result links survive reload and browser disconnect.

* `failed`: terminal provider/processing failure; inspect raw attempts and existing
  pipeline records before further work.
* `held_unknown`: worker interruption before a durable aggregate result; no paid
  replay is attempted. Original reservations and responses stay available.
* `awaiting_index`: aggregate result is durably archived. The worker can retry
  indexing it without a provider call, including after policy revocation.
* `blocked_policy`: configuration/code/authorization no longer matches.
* `paused_disk`: preparation stopped at the disk floor before a provider call.

On restart the worker reconciles interrupted jobs while holding its exclusive
lock. A saved aggregate is indexed; an uncertain execution is held. Gemini SDK
retries are disabled; outer exact-request retries hit a retained reservation and
never reach the network. OpenAI keeps its existing exact request/failed-reservation
ledger and receives an additional on-demand execution namespace/call allowance.
Existing campaign workers do not receive that namespace or policy.

## Verification and deployment boundary

`python -m unittest test_on_demand test_native_issues test_article_pipeline
test_paired_history test_historical_divergence` exercises offline fixtures. It
does not call a provider, download a model or mutate the research database.
`test_on_demand_browser.py` is a localhost-only, conspicuously labelled synthetic
UI harness backed by the real durable queue. It never imports an inference
adapter and is not a public route or a production worker mode.

`scripts/on_demand_vps.py stage` copies only source assets into an immutable,
checksum-verified release. It neither activates providers nor changes running
services. Production cutover must preserve the automatic main updater's retained
operator overrides and avoid parallel native/VPS mutations. Keep the paused
OpenAI campaign and separately owned Winter War historical Gemini backfill
unchanged. Staging/tests do not establish that a paid production request ran.

# Research viewer on a VPS

This package deploys the existing Python research application. It does not alter the native MediaWiki stack in `infra/wiki`, the developer database compose file, or the independently runnable viewer. Use a Linux x86-64 VPS with Docker Engine and Compose v2. The CPU image pins [Gunicorn 27.0.1](https://pypi.org/project/gunicorn/27.0.1/) and includes ONNX/CTranslate2 dependencies; it does not contain Wikipedia data, model weights, credentials or prepared findings.

**Build on the VPS, not on the low-space development laptop.** The Linux image build has not been run locally. Leave room for the image, model caches, imported database, backups and temporary build layers; inspect `df -h` and `docker system df` on the chosen server first. Do not run a broad Docker prune or delete existing server data to make space.

## Services and public boundary

- `db`: the same pinned MariaDB 12.3.3 family used by the research runtime, including `VECTOR(384)` support. A named volume persists its database. No database port is published.
- `web`: one Gunicorn process with four threads, bound to port 8080 inside the container and localhost only on the VPS. A mounted persistent session secret keeps CSRF/session tokens stable across restarts. The app image and data/model mounts are read-only; `/tmp` is bounded writable memory.
- `init`: an explicit setup-profile job creating/upgrading existing schemas idempotently. It does not download a dataset/model, seed demo content, enqueue work, call providers.
- `history-worker`, `title-worker`, `highlight-worker`: explicit worker-profile jobs. Each exits after draining the selected existing queue or cached-work selection; none restarts in a loop. Starting `web` never starts these services.
- `embedding-worker`: explicit offline-profile job filling missing E5 snapshot passage vectors from the already installed model; no provider secret. Its default is a five-topic pilot, not the complete corpus.
- `catalog-seed`: explicit catalog-profile job importing checksum-locked precomputed BGE-M3 article vectors into the separate `library` database. Its default is a 20-vector pilot. Set `NEOWIKI_DATASET_LOCK` to the repository's lock file and create its dedicated `library_seed` account/secret before use. It never computes embeddings or changes MediaWiki histories.

The new database defaults to MHNSW M=16 for newly created indexes and ef_search=80, with a 256 MiB vector cache and 512 MiB InnoDB buffer pool. Existing imported vector indexes retain their original M; changing the server default does not rebuild them. The BGE seed explicitly creates its own index with M=16. These are retrieval settings, not embedding dimensions or a guarantee of perfect recall.

The production WSGI adapter allows the current explorer's stored-data reads, article/tracker pages, static assets and CSRF-protected local translation. It denies preparation/verification/review mutations, legacy raw history/details/cache routes, enrichment and private spending dashboards. The reader has no provider secret mount, strips provider-key environment variables and refuses a root `.env`/`.env.local`. Its provider call function is also disabled. Local query embeddings and local translation can run; their results remain model-assisted. An absent local model is not permission to download or call a provider while browsing.

All non-public maintenance stays in explicit CLI jobs. Existing local dev routes remain unchanged outside this WSGI adapter. Legacy tracker mutation controls, if visible, are unavailable in this public reader. The main explorer's review flags are browser-local.

## Configure the selected server

Read the Hostinger VPS inventory before choosing a target. This is a generic VPS/SSH deployment, not Hostinger's Shared/Cloud website upload API. Do not overwrite an existing server application or import into an existing database without inspecting and backing it up first.

On the selected VPS, clone the reviewed branch/commit, then use these commands from the repository root. Commands below use a shell alias only for brevity:

```sh
sudo install -d -m 0750 /etc/neowiki /etc/neowiki/secrets
sudo install -d -m 0750 -o 10001 -g 10001 /srv/neowiki/data /srv/neowiki/model-cache
sudo cp tools/language-gap-explorer/.env.example /etc/neowiki/runtime.env
sudo chmod 0600 /etc/neowiki/runtime.env
# Edit deployment paths, port and proxy settings; this file contains no API key.
sudoedit /etc/neowiki/runtime.env
```

Generate database and session secrets directly into files, without printing them:

```sh
sudo sh -c 'umask 027; openssl rand -hex 32 > /etc/neowiki/secrets/db-root-password'
sudo sh -c 'umask 027; openssl rand -hex 32 > /etc/neowiki/secrets/db-password'
sudo sh -c 'umask 027; openssl rand -hex 32 > /etc/neowiki/secrets/session-secret'
sudo chown root:10001 /etc/neowiki/secrets/db-root-password /etc/neowiki/secrets/db-password /etc/neowiki/secrets/session-secret
sudo chmod 0640 /etc/neowiki/secrets/db-root-password /etc/neowiki/secrets/db-password /etc/neowiki/secrets/session-secret
alias nw='docker compose --env-file /etc/neowiki/runtime.env -f tools/language-gap-explorer/compose.vps.yaml'
nw config --quiet
nw build web
nw up -d --wait db
```

Compose file-backed secrets retain their host ownership and permissions; its `uid`/`gid` options cannot remap ordinary bind-mounted files. The image runs as UID/GID **10001:10001**, so the `root:10001`, `0640` ownership/mode above lets app containers read their mounted files without making them world-readable. Verify after mounting with `nw run --rm init python -c 'import os; from pathlib import Path; print(os.getuid(), os.getgid()); assert Path("/run/secrets/db-password").is_file()'`; the entrypoint already fails if its password is unreadable.

Keep `/etc/neowiki` outside Git. The provider-key file is needed **only** when running paid workers; put an already-authorized key into `/etc/neowiki/secrets/provider-key` using a secure transfer/editor, with owner `root:10001`, mode `0640`. Do not paste it into shell history, logs or a tracked environment file. Database initialization variables apply only when its volume is empty; changing a secret file later does not rotate an existing MariaDB account's password.

## Migrate the current real sample

The current research runtime is a separate ignored root. Migrate its **logical database plus `data/` and `model-cache/`**, not its virtual environment, `.env`, local paths, logs or private reports. Preserve all existing IDs, successful cached results, failed reservations and the `api_call` ledger. A new ledger with old cached evidence would lose the existing reservation/accounting context. Do not regenerate expensive comparisons to populate an empty server.

1. Pause explicit local preparation/title/highlight writers and wait for their current work to finish. Record the reviewed source commit, database version and selected run IDs. Back up the destination separately before importing anything.
2. Create a consistent logical dump of the complete research database using `mariadb-dump --single-transaction --quick --hex-blob --routines --events --triggers`. Use a mounted client option file or `MYSQL_PWD` only inside the source DB container; do not put passwords in command arguments. Use a client version matching MariaDB 12.3.3 and validate the dump's versioned-table support. This is distinct from Wikipedia revision timestamps.
3. Transfer the dump over SSH to private server storage, outside this repository/webroot. Transfer `data/` and `model-cache/` intact, retaining revision manifests/text, cached vectors and translation provenance. Do not transfer a runtime-root `.env` file.
4. Import into the newly initialized, dedicated research database. The example name below matches `.env.example`; adjust it if `DB_NAME` differs:

```sh
# The password is read inside the container, not exposed in host argv or output.
nw exec -T db sh -ec 'export MYSQL_PWD="$(cat /run/secrets/db-root-password)"; exec mariadb --user=root language_gaps' < /srv/neowiki-backups/research.sql
sudo chown -R 10001:10001 /srv/neowiki/data /srv/neowiki/model-cache
nw run --rm init
```

The import must include data as well as schemas. Initialization only adds missing tables/columns; it never creates fake findings. The separate system-versioned assessment-state experiment is outside this deployment branch and is not initialized or seeded here.

### Low-disk transfer

Do not create a full dump or tar archive on the development laptop. Once SSH is authenticated and the target is verified, stream the source container's dump stdout directly into SSH writing a private VPS `research.sql.part`, then rename it only after both producer and SSH exit successfully. Use a binary `subprocess.Popen` pipe from Python (producer `stdout=PIPE`, consumer `stdin=producer.stdout`), not a Windows PowerShell text pipeline; do not use `capture_output` or read the entire dump into memory. Check both return codes, stop on a failed/truncated stream and import only the completed server-side file. An SSH disconnect must never be treated as a completed migration.

Stream `data/` and `model-cache/` using the same binary pipe pattern with tar, extracting only into a newly prepared dedicated runtime directory on the VPS. No local archive is necessary. Transfer no `.env`, private reports or virtual environment. Pause source writers while taking this consistent migration set; resumable large-file transfer is also suitable if available. The source research database is separate from the native wiki database: identify the source container/database before dumping, and never point this migration at `infra/wiki`.

## Shared embedding database and team access

The migrated `language_gaps` database is the shared research embedding store. Existing `article` records, `passage` vectors and model identity travel with the logical dump; cached historical vectors/passages and evidence tables travel too. An image build does not seed embeddings. Do not re-import or regenerate all embeddings just because a teammate connects. Record and compare these source/destination checks before inviting the team:

```sql
SELECT lang, COUNT(*) AS articles FROM article GROUP BY lang;
SELECT model, lang, COUNT(*) AS passages FROM passage GROUP BY model, lang;
SELECT COUNT(*) AS historical_vectors FROM divergence_vector;
SELECT COUNT(*) AS stored_occurrences FROM paired_occurrence;
SELECT COUNT(*) AS stored_runs FROM paired_run;
```

These are actual seeded counts, not a claim that every corpus article has been embedded or compared. Keep the 384-dimensional multilingual E5 model consistent with the existing vectors; a different query model requires its own compatible index, not relabeling the stored embeddings.

Most teammates should use the deployed reader URL. For SQL/vector experimentation, give each teammate a separate scoped DB account and SSH access; do not share the web/worker or root password. A reader account can start with `SELECT` on `article` and `passage`, with specific additional cached-evidence tables granted only when needed. Do not grant blanket research-database access to expose the private provider ledger. Granting write/preparation access is a separate explicit operation; paid workers stay controlled and metered.

If SQL access is needed, publish MariaDB **only on VPS loopback**, using an operator-owned Compose override outside Git:

```yaml
# /etc/neowiki/team-db.yaml
services:
  db:
    ports: ["127.0.0.1:3311:3306"]
```

Apply this override only after reviewing the existing DB service configuration, or include the equivalent packaged `compose.team-db.yaml`. It is not enabled by the base package. A teammate can then tunnel `ssh -N -L 3311:127.0.0.1:3311 USER@VPS` and connect to `127.0.0.1:3311`, database `language_gaps`, using their own DB account. Keep port 3306/3311 closed publicly. Use local port 3311 to avoid colliding with the existing laptop research database on 3310.

For a local research process, set `DB_HOST=127.0.0.1`, `DB_PORT=3311`, `DB_NAME=language_gaps`, `DB_USER` to the teammate account and `DB_PASSWORD` through an untracked runtime secret/environment. These settings are for this Python research app only. **Do not change the native MediaWiki `MW_DB_*` settings or its database volume.** Read-only SQL access cannot run schema initializers or preparation jobs; the server operator runs those explicitly.

For a genuinely fresh installation, dataset acquisition/model installation and comparison preparation are separate explicit operations. They can be slow and consume substantial disk/provider budget. Do not run `setup.ps1` or seed-demo commands on the production reader. Existing models are preferred. To explicitly download missing local models on the VPS (no paid inference):

```sh
nw run --rm init python -c 'from prepare import embedding_model; embedding_model()'
nw run --rm init python local_translation.py --install
```

## Start and verify the reader

```sh
nw up -d --wait web
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/explore
curl --fail http://127.0.0.1:8080/explore/api/showcase
# A private dashboard/raw history/preparation call must remain unavailable:
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/reviews
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/explore/api/history
curl -X POST -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/reviews/Q134949
nw ps
nw logs --tail=80 web
```

The last three requests should return 404. `/healthz` is readiness for the web process and DB connection, not a claim the corpus is prepared. Also inspect a real prepared article's histogram, keyword/local hybrid search, a monthly issue list, exact evidence and its historical tracker link. Verify desktop/mobile, translation, source revisions and browser Back without starting a worker. Compare source/destination article, run, occurrence and cache counts. Test local semantic/translation inference on the **Linux** model cache; copied Windows cache paths/symlinks may need repair using the same model versions, never by silently downloading during browsing.

Use an SSH tunnel for initial browser QA (`ssh -L 8080:127.0.0.1:8080 VPS`). Set `NEOWIKI_COOKIE_SECURE=0` only for this HTTP test and recreate web. For public access, configure an existing or separately installed reverse proxy with HTTPS to `127.0.0.1:8080`, restore `NEOWIKI_COOKIE_SECURE=1`, and use `NEOWIKI_TRUST_PROXY=1` only when there is exactly one trusted proxy. Keep port 8080 and MariaDB unavailable from the public network. TLS/domain setup is a separate deployment step requiring the actual target, not a guessed hostname.

## Explicit background work

Workers receive the provider key; the web service never does. These commands are deliberate paid-work actions, not startup prerequisites:

```sh
# Inspect prepared/queued work without provider access:
nw run --rm init python article_pipeline.py status
# Drain already queued article and naming jobs:
nw --profile workers run --rm history-worker
nw --profile workers run --rm title-worker
# Cached highlight preparation for the curated showcase, explicitly requested:
nw --profile workers run --rm highlight-worker
# A narrower explicit highlight job can override its command:
nw --profile workers run --rm highlight-worker python evidence_highlights.py --topic Q134949 --workers 2
```

Enqueueing new corpus/history work is a separate decision. No service auto-enqueues all articles. Worker concurrency remains bounded by the existing DB-backed provider locks and retained reservations. An optional `NEOWIKI_API_TOTAL_LIMIT_USD` cap is configuration, not a reset. Failed/held jobs require the existing explicit resume policy; restarting a container must not erase reservations or blindly retry failures.

## Updates and backups

Packaging policy checks run without a database, downloads or provider calls: from this app directory, run `python -m unittest deploy.test_runtime`. Validate Compose separately with `docker compose --env-file .env.example -f compose.vps.yaml config --quiet`; this parses configuration without building images or contacting the Docker daemon. These checks do not replace a real Linux image build and remote data/model migration smoke test.

Before an update, record the current image/commit and take a consistent database dump plus data/model-cache backup. Build the new image remotely, run the explicit init service, then recreate web. Run the health/public-route/source-identity checks again. Retain the old image and database backup for rollback; schema changes may require restoring the matching database backup. Do not use `docker compose down -v`: it destroys the research DB volume. Ordinary `down`/`up` preserves it. The app has bounded container logs; database and runtime-volume backups still need an operator retention policy.

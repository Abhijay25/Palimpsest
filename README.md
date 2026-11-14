# Palimpsest

An optional [NeoWiki divergence explorer](tools/divergence-explorer/README.md) visualizes historical differences between language editions. Run it independently with the included real-data sample; no wiki runtime or API key is required.

Local MediaWiki infrastructure for the team, with separate Finnish, Swedish and English wikis and one persistent MariaDB server. The approved baseline includes Vector 2022, local accounts, source/visual editing, history/diffs, discussions, watchlists, uploads, references, Lua and online Commons. See the [scope](docs/infra/spec.md) for the feature matrix and boundaries.

## Start locally

Install Docker Desktop (or Docker Engine with Compose) and Python 3.11+. Run from a clone of this repository:

```sh
python3 scripts/wiki setup
python3 scripts/wiki verify --scope runtime
```

Open Finnish at <http://127.0.0.1:8081>, Swedish at <http://127.0.0.1:8082> and English at <http://127.0.0.1:8083>. Setup initializes empty functional wikis; downloading or importing the dataset is separate. Initial pulls and online Commons require internet.

Generated databases, uploads, configuration and credentials live in ignored `.local/wiki`. Each wiki has a local `admin` account; its generated password is in `.local/wiki/secrets/<language>/admin-password`. Keep these local files private. New accounts can also be created through the wiki UI.

```sh
python3 scripts/wiki down       # stop; preserve data
python3 scripts/wiki up         # restart
python3 scripts/wiki update     # run schema updates
```

For a separate environment, put all shared options before the command:

```sh
python3 scripts/wiki --project teammate --data-root /path/to/wiki-data --ports 9081,9082,9083 setup
```

Reuse the same options for later commands. `reset --confirm-project <name>` deletes only that named runtime's databases, configuration, credentials and uploads; it preserves acquired source datasets/history. Read [verification quickstart](docs/infra/quickstart.md) for platform/resource details and isolated test commands.

## Dataset and original history

Downloaded content retains the release README and its notices: Wikipedia text is CC BY-SA 4.0, with credit and original article links retained in the source manifests. Consult the fetched `dataset/raw/README.md` and the [release](https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/tag/s-2026-10).

The locked `s-2026-10` release contains 29,460 pages: 19,285 Finnish, 4,921 Swedish and 5,254 English. Its Markdown snapshots are research assets; they are not a MediaWiki SQL backup or the original edit histories.

```sh
python3 scripts/wiki dataset fetch
python3 scripts/wiki history probe-anchors
python3 scripts/wiki history acquire --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data support --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki data import --sample-manifest tests/data/fixtures/sample-corpus.json
python3 scripts/wiki verify --scope sample --sample-manifest tests/data/fixtures/sample-corpus.json
```

These commands use an explicit six-page real sample, with original public histories through each S revision anchor. Dependency acquisition is budgeted and resumable; incomplete dependencies/imports produce a nonzero result and an explicit report. Preserve the data root and rerun to resume. Source IDs and local IDs are recorded separately. See [pipeline instructions](infra/data/README.md) for reports, recovery and explicit full-corpus options.

**Full S import and complete original-history reconciliation are outstanding.** Runtime health or a passing sample does not certify full seeding. Use `verify --scope full` to expose missing full-corpus work; see [verification evidence](docs/infra/verification.md) for actual tested behavior and limitations.

## Development and checks

```sh
python3 -m unittest discover -s tests/runtime -v
python3 -m unittest discover -s tests/data -v
python3 -m unittest discover -s tests/infra -v
```

The test quickstart documents opt-in Docker/browser checks. Runtime images are pinned by multi-platform digest. No host PHP, database or data-science packages are required. Custom extensions can be mounted through `infra/wiki/extensions/load.php`, followed by `scripts/wiki update`; upstream MediaWiki core stays in its image.

The [specification](docs/infra/spec.md), [design](docs/infra/design.md), [contracts](docs/infra/contracts.md), [task plan](docs/infra/tasks.md) and [worker registry](docs/infra/orchestration.md) record the approved SDD process. This infrastructure does not implement the separate Wikipedia Blame prototype.

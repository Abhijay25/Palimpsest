# Palimpsest Library

A separate localhost frontend for exploring real Wikipedia subjects as books in a spatial library. Enter a book to walk through its imported revisions, newest to oldest; open an edition to read the full article and inspect wording with the repository's native inline Blame.

The initial collection contains **3 topic-books, 9 language articles and 133 original public revisions**. Every book has English, Finnish and Swedish. The surrounding shelves are atmosphere; selectable books and editions always identify real records.

## Run

Requirements: Docker with Compose, Python 3, Node **22.12+** (tested 22.23.3), and Ollama on `PATH`. Vite also supports Node 20.19+. Allow approximately 1.2 GB for the bge-m3 model, plus the locked datasets and isolated wiki/database storage. Initial setup needs internet access to public release assets, Wikipedia APIs, images and the model registry.

On the delivery Mac, the default Homebrew Node/Docker links were unusable. These installed paths were verified; use them when resuming on this host (other machines should use their own working installations):

```sh
export PATH="$HOME/.nvm/versions/node/v22.23.3/bin:/Applications/Docker.app/Contents/Resources/bin:/opt/homebrew/Cellar/ollama/0.9.6/bin:$PATH"
```

From the repository root, with working `node`, `npm`, `docker`, and `ollama` commands:

```sh
python3 scripts/wiki dataset fetch
cd apps/library
npm ci
npm run setup
npm run build
npm start
```

Open **http://127.0.0.1:5180/**. Setup does not reset existing data. It provisions its own `palimpsest-library` wikis and `palimpsest-library-vector` database, acquires only `corpus.json` histories through their locked S anchors, reconciles local/source revision identities, installs provenance, loads native MariaDB vectors, and prepares Ollama.

The dataset step downloads and validates the locked S assets and builds the existing data tooling image. It does not import all Wikipedia articles. Library extraction rechecks the article/vector asset checksums and admits only the three trilingual Wikidata groups.

For development, stop the production app first, then run `npm run dev`. Vite serves port 5180 and proxies the Node backend at 5181. Keep the supporting services running.

| Service | Local address |
| --- | --- |
| Library | http://127.0.0.1:5180 |
| Finnish / Swedish / English MediaWiki | http://127.0.0.1:48181 / 48182 / 48183 |
| MariaDB vector catalog | 127.0.0.1:48184 |
| Feature Ollama | http://127.0.0.1:11435 |

Generated data, credentials, histories, model files, logs and evidence live in ignored `.local/library/` at the repository root. Passwords are generated into private files; do not copy them into frontend configuration. Existing default wikis, Blame runtimes and the separate fictional prototype use other ports and are preserved.

## Explore

- Scroll to drift through the lattice, then choose a labeled topic-book. Search accepts a topic or question in English, Finnish or Swedish and performs actual Ollama bge-m3 embedding plus MariaDB cosine retrieval.
- In a corridor, scroll, use arrow/Page keys, or use the history slider. Each edition appears once: newest left, next right, then older pairs farther ahead. `Newest` and `Oldest` reach the ends. At most 28 edition objects are active.
- Open a dated book or choose `Open this edition`. The reader pauses the camera. Drag across article text and choose `Inspect selected text`, or focus a highlighted word and press Enter/Space. Native Blame shows the exact quote, revision groups and relevant history beneath its paragraph.
- Escape first closes inline inspection, then the book. Closing restores the corridor camera and focus. The reader's footer links to the exact local Palimpsest revision and its separately verified original Wikipedia revision.
- Switching language opens that language's latest **imported** edition, announces its date and clears the previous selection. Translations have independent histories.
- `List view`, narrow screens and reduced-motion preferences provide the same catalog, editions and reader without 3D. WebGL failure switches to this route automatically.

Color means the revision that last changed the wording. It is accompanied by revision/date labels and does not mean truth, importance or editor identity. Generated/template text, unsupported mappings and uncertain moves/reverts retain the native explicit limitations.

## Resume setup and diagnose

Run `npm run setup -- --phase NAME` for `runtime`, `extract`, `histories`, `support`, `import`, `provenance`, `vectors`, or `model`. Dependencies are sequential: histories/support precede import; verified import precedes provenance; extraction plus provenance precede vectors. If a phase fails, inspect `.local/library/NAME.log` before continuing. Public API rate limits preserve resumable checkpoints.

Supporting template/module closure is **incomplete in this delivery**. The full original article text is available, but some citations, infoboxes and generated components can show missing dependencies. This is separate from the verified 133-revision article-history coverage. The native UI refuses attribution for unsupported rendered regions. Resume `support`, then `import` and `provenance` after upstream backoff; reverify before claiming rendering completeness. A clean-machine run was not repeated after delivery; the individual preparation phases were exercised on this host.

Search can take around 24 seconds on a cold model load; measured warm queries took approximately 0.1–0.8 seconds on this host. A missing model/database produces an error, without substituting canned results. The finite three-topic projection is deliberately specific to this corpus; adding topics requires generalizing the layout and revalidating all languages/history mappings.

To stop only the feature's containers while preserving data, from the repository root:

```sh
python3 scripts/wiki --project palimpsest-library --data-root "$PWD/.local/library/wiki" --ports 48181,48182,48183 down
docker compose --project-name palimpsest-library-vector --env-file .local/library/database.env -f apps/library/compose.yaml down
```

Stop a foreground app/Ollama process with Ctrl-C in its own terminal. Do not use global Docker cleanup or stop unrelated services.

## Verify

From `apps/library`:

```sh
npm test
npm run build
npm run verify:live
```

The first command checks provenance rejection, chronology, 705 alternating slots, semantic layout and multilingual grouping without network services. `verify:live` requires the real prepared runtime and records all nine article/history analyses, source identity, frozen relevance queries and route guards in `.local/library/evidence/native.json`.

For the actual Chromium acceptance suites, from the repository root:

```sh
docker build -t palimpsest-library-browser:1.65.1 -f tests/infra/browser/Dockerfile tests/infra/browser
docker run --rm --entrypoint python \
  -e LIBRARY_BROWSER_ORIGIN=http://host.docker.internal:5180 \
  -v "$PWD/apps/library:/repo/apps/library:ro" \
  -v "$PWD/.local/library/evidence:/evidence" \
  palimpsest-library-browser:1.65.1 /repo/apps/library/tests/browser_acceptance.py
docker run --rm --entrypoint python \
  -e LIBRARY_BROWSER_ORIGIN=http://host.docker.internal:5180 \
  -v "$PWD/apps/library:/repo/apps/library:ro" \
  -v "$PWD/.local/library/evidence:/evidence" \
  palimpsest-library-browser:1.65.1 /repo/apps/library/tests/spatial_acceptance.py
docker run --rm --entrypoint python \
  -e LIBRARY_BROWSER_ORIGIN=http://host.docker.internal:5180 \
  -v "$PWD/apps/library:/repo/apps/library:ro" \
  -v "$PWD/.local/library/evidence:/evidence" \
  palimpsest-library-browser:1.65.1 /repo/apps/library/tests/guard_acceptance.py
```

These macOS Docker Desktop commands access the localhost app through `host.docker.internal`. Linux requires a suitable host-network address/configuration. Browser tests read the real corpus; they do not seed replacement content or fabricate response data. The guard suite delays one unchanged real response to exercise a language race and uses a browser Range over actual generated text to verify refusal; native gestures are tested separately. The mixed-word case freezes original contributor-revision identities independently of rendered output. The spatial suite uses software WebGL for functional coverage; actual GPU performance is measured separately in the native browser.

See [verification](../../docs/library/verification.md), [design](../../docs/library/design.md), and [prioritized future work](../../docs/library/future-work.md).

For the shared VPS embedding source, follow [shared database configuration](../../docs/shared-embeddings.md). Library uses BGE-M3 article vectors in `library`; the research explorer's E5 passage vectors are a separate schema/model. Preserve your verified catalog and wiki provenance when switching the private database configuration. Do not rerun setup to switch connections: setup replaces that configuration with local defaults.

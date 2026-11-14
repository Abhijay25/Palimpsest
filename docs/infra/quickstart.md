# Infrastructure verification quickstart

This page covers the isolated infrastructure checks. It does not download or import the full S corpus. Full-corpus acquisition is a separate, explicitly requested operation and is not part of ordinary CI.

## Prerequisites

- Python 3.11 or newer. The deterministic contract checks use only the Python standard library; there are no host Python package installs.
- Docker Desktop or Docker Engine with Compose v2 for runtime checks. Browser checks use the version-locked Playwright runner described below.
- For Docker checks, allow about 4 CPUs and 8 GB RAM. Reserve at least 10 GB for images and an empty runtime. The 50 GB planning floor in the design applies to later full-history work, not this fixture suite.
- Ports 38081–38083 must be available for the worker-C test project. The test data root is separate from application data and caches.

On macOS, make Docker Desktop's bundled CLI and credential helpers available without installing host packages:

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

## Deterministic checks

From the repository root, run the contract fixtures and isolated dispatcher tests:

```sh
python3 -m unittest discover -s tests/infra -v
python3 scripts/wiki --help
```

These checks use synthetic, three-language manifests and histories. They verify source-to-local identity mappings, content hashes, anchor presence, UTC timestamps, visible-empty versus hidden content, exact coverage counts, and failure on removed history or mappings even if C5 claims completion. Dispatcher tests run a copied launcher with isolated stub children to observe routing, help forwarding, exit-code propagation, invalid-scope handling, and relative-path resolution. They do not start Docker or contact Wikimedia.

## Isolated Docker runtime checks

The opt-in runtime suite uses project `palimpsest-c`, ports 38081–38083, and its own `.local/infra-test-c` data root. Check that no earlier `palimpsest-c` environment is active before starting. The suite exercises three-language startup, API identity/readiness, repeat setup, shutdown, and persisted API access. It does not use global Docker cleanup or shared dataset caches.

```sh
PALIMPSEST_RUN_DOCKER=1 python3 -m unittest tests.infra.test_docker_runtime -v
```

The suite is excluded from ordinary CI. The workflow's manual `docker_runtime` input runs it on a clean Linux runner. It checks distinct language/database routing and API access across first setup, repeated setup and restart. A local failure may leave the named project stopped with its volumes preserved for inspection; it will never run global prune commands.

The live-source sample acceptance command will be added after B publishes the concrete C2–C5 artifact handoff path. Until then, no test guesses where producer manifests are stored or how their output is serialized. When enabled, this tier must use an explicitly selected three-language sample, require network access to release assets and public APIs, and stay out of ordinary CI. It must never switch a full request to a sample. A passing sample is not evidence that all 29,460 S pages or their histories are complete.

## Browser acceptance

Browser acceptance is a separate opt-in integration tier. Its runner starts and removes its own isolated worker-C runtime. It runs a pinned Playwright Python package and matching browser binaries inside the official `mcr.microsoft.com/playwright/python:v1.65.1-noble` image; the host needs Docker, not Python browser packages. Tests run independently against fi, sv and en and use newly generated local accounts and the same unique page/account names in each wiki to prove identity isolation. They exercise source and visual edits, history/diff, talk post/reply, watchlist updates from a second user, upload/display, and the core administrator-only protect boundary. Synthetic test pages and users stay in the worker-C runtime.

The image tag pins Playwright 1.65.1 and its bundled browser set: Chromium 158.0.8127.18, Firefox 159.0, and WebKit 27.2. The browser suite uses Chromium. Official Playwright images support Linux amd64 and arm64; Docker Desktop on macOS ARM64 can use the arm64 image. Browser verification requires a running worker-C runtime and is not included in normal CI. Do not reuse a personal wiki or production credentials. See the [Playwright Docker guide](https://playwright.dev/python/docs/docker) and [v1.65.1 release](https://github.com/microsoft/playwright-python/releases/tag/v1.65.1) for the matching package and browser image versions.

The runner command owns its temporary `palimpsest-c-<run-id>` project, port allocation, data root, browser-state file, and uniquely tagged browser image. It creates accounts, edits, discussion, watchlist state and an upload in each wiki; then it shuts down and restarts the same project and checks those records again. It runs `down` and an exact-project `reset` after the checks, then removes only the image it built. On macOS, ensure Docker Desktop's CLI/helper directory is on `PATH` as shown above.

```sh
python3 tests/infra/run_browser_acceptance.py
```

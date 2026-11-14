# Test fixture lessons

- A copied PNG literal had a bad IDAT checksum and would have made the upload test fail for the wrong reason. Generate binary image fixtures from chunks and verify their CRCs before using them in browser acceptance.
- MediaWiki Siteinfo does not publish a `dbname` field. Check the current API contract before asserting undocumented response fields; verify declared database isolation through unique C1 identities and cross-wiki behavioral probes.
- An API 200 through a container gateway does not prove browser pages can follow MediaWiki's canonical-host redirects. Run a page-flow probe; for containerized browser tests, set the disposable runtime's canonical URL to its reachable gateway before relying on navigation or cookies.
- VisualEditor can show a first-run welcome dialog asynchronously, then leave `.mw-page-container` inert briefly after the dialog closes. Always wait for and dismiss the dialog, wait until that class-based page container is no longer inert, then target the pinned editor root `.ve-ce-rootNode[role="textbox"][contenteditable="true"]`.
- On macOS, `/tmp` resolves to `/private/tmp`; validate temporary cleanup against the resolved parent and unique prefix rather than comparing the unnormalized `/tmp` string.
- Runtime `setup` may regenerate managed settings on rerun. Reapply disposable browser-only config overrides after every setup, then restart that project before browser navigation.
- Check the target worktree's actual public entrypoint before cross-worktree integration probes; sibling worktrees may expose `runtime.py` without the `scripts/wiki` dispatcher.
- Match browser controls to the pinned application's current accessible DOM. A stale VisualEditor class selector can miss a working editor; verify the visible toolbar, accessible textbox, save flow, and persisted article outcome.
- Check case-sensitive extension class names against the pinned source: DiscussionTools 1.46 uses `.ext-discussiontools-ui-replyWidget` with a capital `W`, not the older guessed lowercase selector.
- Before saving a browser-edited page, wait for the full marker in VisualEditor's document model as well as the visible editor, then assert Save is enabled. Rapid input can update the DOM before the model catches up; click within existing article text, use the editor's end-of-document shortcut, and pace keyboard input.
- Linux Docker cannot route `host.docker.internal:host-gateway` to a service bound only on host loopback. Run the browser container with host networking and use `127.0.0.1`; retain Docker Desktop's host alias on macOS.

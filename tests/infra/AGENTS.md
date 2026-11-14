# Test fixture lessons

- A copied PNG literal had a bad IDAT checksum and would have made the upload test fail for the wrong reason. Generate binary image fixtures from chunks and verify their CRCs before using them in browser acceptance.
- MediaWiki Siteinfo does not publish a `dbname` field. Check the current API contract before asserting undocumented response fields; verify declared database isolation through unique C1 identities and cross-wiki behavioral probes.
- An API 200 through a container gateway does not prove browser pages can follow MediaWiki's canonical-host redirects. Run a page-flow probe; for containerized browser tests, set the disposable runtime's canonical URL to its reachable gateway before relying on navigation or cookies.
- VisualEditor can show a first-run welcome dialog before exposing its editable surface. Dismiss that supported onboarding step before asserting editor controls.
- On macOS, `/tmp` resolves to `/private/tmp`; validate temporary cleanup against the resolved parent and unique prefix rather than comparing the unnormalized `/tmp` string.

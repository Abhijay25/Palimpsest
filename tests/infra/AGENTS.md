# Test fixture lessons

- A copied PNG literal had a bad IDAT checksum and would have made the upload test fail for the wrong reason. Generate binary image fixtures from chunks and verify their CRCs before using them in browser acceptance.
- MediaWiki Siteinfo does not publish a `dbname` field. Check the current API contract before asserting undocumented response fields; verify declared database isolation through unique C1 identities and cross-wiki behavioral probes.

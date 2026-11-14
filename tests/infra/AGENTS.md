# Test fixture lessons

- A copied PNG literal had a bad IDAT checksum and would have made the upload test fail for the wrong reason. Generate binary image fixtures from chunks and verify their CRCs before using them in browser acceptance.

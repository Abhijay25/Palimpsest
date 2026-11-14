# Blame test notes

- Mock `urllib` HTTP failures with the real `HTTPError` type and an in-memory body; cover structured Action API errors and non-JSON status fallback without opening sockets.
- Use the pinned Playwright signature (`arg=` for `wait_for_function`) and match observed text nodes exactly; do not normalize paragraph breaks without runtime evidence.
- Do not count self-rendered UI as product acceptance; exercise the producer or an explicitly seeded read-only native page. Compute fill separation and owner lineage from rendered output rather than matching classes or assumed same-revision events.

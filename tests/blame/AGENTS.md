# Blame test notes

- Mock `urllib` HTTP failures with the real `HTTPError` type and an in-memory body; cover structured Action API errors and non-JSON status fallback without opening sockets.

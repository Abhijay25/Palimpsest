"""Stable, opt-in caching for evidence read by audit judges."""

import hashlib
import json
import os
from collections import OrderedDict
from pathlib import Path
from typing import Final, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_CACHE_ENV: Final = "PALIMPSEST_EVIDENCE_CACHE_DIR"
_MEMORY_CACHE_SIZE: Final = 512
_MEMORY_CACHE: OrderedDict[tuple[str, str], object] = OrderedDict()


def _normal_url(value: str) -> str:
    """Canonicalize harmless URL spelling differences without changing its meaning."""
    parts = urlsplit(value.strip())
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, query, "")
    )


def _normal_value(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return [_normal_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normal_value(item) for key, item in sorted(value.items())}
    return value


def evidence_cache_key(endpoint: str, url_or_query: str, parameters: object) -> str:
    """Return the stable key for one evidence response."""
    payload = {
        "endpoint": endpoint.strip(),
        "url_or_query": _normal_url(url_or_query),
        "parameters": _normal_value(parameters),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EvidenceCache:
    """Cache successful JSON-safe evidence responses on disk only when opted in."""

    def __init__(self, namespace: str = "") -> None:
        self._namespace = namespace

    def get(
        self, endpoint: str, url_or_query: str, parameters: object
    ) -> object | None:
        key = evidence_cache_key(endpoint, url_or_query, parameters)
        directory = os.environ.get(_CACHE_ENV)
        if directory:
            try:
                return cast(
                    object,
                    json.loads((Path(directory) / f"{key}.json").read_text("utf-8")),
                )
            except (OSError, json.JSONDecodeError):
                return None
        memory_key = (self._namespace, key)
        value = _MEMORY_CACHE.get(memory_key)
        if value is not None:
            _MEMORY_CACHE.move_to_end(memory_key)
        return value

    def put(
        self, endpoint: str, url_or_query: str, parameters: object, value: object
    ) -> None:
        """Store only a caller-confirmed successful response."""
        key = evidence_cache_key(endpoint, url_or_query, parameters)
        directory = os.environ.get(_CACHE_ENV)
        if directory:
            target_dir = Path(directory)
            path = target_dir / f"{key}.json"
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(value, ensure_ascii=False, sort_keys=True), "utf-8"
                )
                temporary.replace(path)
            except OSError:
                return
            return
        memory_key = (self._namespace, key)
        _MEMORY_CACHE[memory_key] = value
        _MEMORY_CACHE.move_to_end(memory_key)
        while len(_MEMORY_CACHE) > _MEMORY_CACHE_SIZE:
            _MEMORY_CACHE.popitem(last=False)

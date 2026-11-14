"""Small, opt-in persistent cache for complete API audit responses."""

import hashlib
import json
import os
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from palimpsest.judge import PROMPT_VERSION

_CACHE_ENV: Final = "PALIMPSEST_RESULT_CACHE_DIR"


def _relevant_environment() -> dict[str, str]:
    """Configuration that can affect an audit, excluding credentials and cache path."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("PALIMPSEST_", "GEMINI_"))
        and key not in {_CACHE_ENV, "GEMINI_API_KEY"}
    }


def result_cache_key(endpoint: str, request: BaseModel) -> str:
    """Hash all request material and behavior-changing public configuration."""
    payload = {
        "endpoint": endpoint,
        "prompt_version": os.environ.get("PALIMPSEST_PROMPT", PROMPT_VERSION),
        "request": request.model_dump(mode="json"),
        "environment": _relevant_environment(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_result(endpoint: str, request: BaseModel) -> dict[str, object] | None:
    """Read one response, or return None when caching is disabled or unavailable."""
    directory = os.environ.get(_CACHE_ENV)
    if not directory:
        return None
    path = Path(directory) / f"{result_cache_key(endpoint, request)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_result(endpoint: str, request: BaseModel, response: BaseModel) -> None:
    """Atomically persist a complete response when the optional cache is enabled."""
    directory = os.environ.get(_CACHE_ENV)
    if not directory:
        return
    target_dir = Path(directory)
    path = target_dir / f"{result_cache_key(endpoint, request)}.json"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                response.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        # The audit is useful without a writable optional cache.
        return

from __future__ import annotations

from typing import Any


_MAX_STR_LEN = 200


def _truncate(text: str, limit: int = _MAX_STR_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def redact_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, dict):
        return {str(key): redact_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return _truncate(str(value))

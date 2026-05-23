from __future__ import annotations

import re
from typing import Any, Iterable

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{6,}\d)\b")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)

_SELF_HARM_TERMS = (
    "self harm", "harm myself","hurt myself",
    "suicide", "kill myself", "end my life",
    "end it","take my life",
)
_HATE_TERMS = (
    "racial slur","ethnic slur","genocide","nazi",
)
_HARASSMENT_TERMS = (
    "harass","stalk","threaten","bully",
)


def detect_safety_flags(text: str) -> list[str]:
    flags: list[str] = []
    if _EMAIL_RE.search(text):
        flags.append("contains_email")
    if _PHONE_RE.search(text):
        flags.append("contains_phone")
    if _URL_RE.search(text):
        flags.append("contains_url")
    lowered = text.lower()
    if any(term in lowered for term in _SELF_HARM_TERMS):
        flags.append("self_harm")
    if any(term in lowered for term in _HATE_TERMS):
        flags.append("hate")
    if any(term in lowered for term in _HARASSMENT_TERMS):
        flags.append("harassment")
    return flags


def unique_flags(flags: Iterable[str]) -> list[str]:
    return sorted(set(flags))


def redact_pii(text: str) -> str:
    redacted = _EMAIL_RE.sub("<redacted_email>", text)
    redacted = _PHONE_RE.sub("<redacted_phone>", redacted)
    return redacted


def redact_pii_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return {str(key): redact_pii_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_pii_payload(item) for item in value]
    return redact_pii(str(value))

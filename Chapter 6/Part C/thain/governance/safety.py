from __future__ import annotations

import re
from typing import Iterable

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{6,}\d)\b")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def detect_safety_flags(text: str) -> list[str]:
    flags: list[str] = []
    if _EMAIL_RE.search(text):
        flags.append("contains_email")
    if _PHONE_RE.search(text):
        flags.append("contains_phone")
    if _URL_RE.search(text):
        flags.append("contains_url")
    return flags


def unique_flags(flags: Iterable[str]) -> list[str]:
    return sorted(set(flags))

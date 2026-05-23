from __future__ import annotations

import logging
from typing import Iterable, Optional

from azure.core.credentials import AzureKeyCredential

try:
    from azure.ai.contentsafety import ContentSafetyClient
    from azure.ai.contentsafety.models import AnalyzeTextOptions
except Exception:  # pragma: no cover - optional dependency at runtime
    ContentSafetyClient = None
    AnalyzeTextOptions = None

logger = logging.getLogger(__name__)


def _normalize_category(value: object) -> str:
    raw = str(value)
    if "." in raw:
        raw = raw.split(".")[-1]
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _has_severity(severity: object) -> bool:
    try:
        return int(severity) > 0
    except Exception:
        return False


def analyze_text(
    text: str,
    *,
    endpoint: str,
    api_key: Optional[str],
    credential,
) -> Optional[list[str]]:
    if not ContentSafetyClient or not AnalyzeTextOptions:
        logger.warning("Azure Content Safety SDK not available.")
        return None
    if not endpoint:
        return None

    if api_key:
        cred = AzureKeyCredential(api_key)
    else:
        cred = credential
    if not cred:
        return None

    try:
        client = ContentSafetyClient(endpoint, cred)
        result = client.analyze_text(AnalyzeTextOptions(text=text))
    except Exception as exc:
        logger.warning("Content Safety analysis failed: %s", exc)
        return None

    flags: list[str] = []
    for item in getattr(result, "categories_analysis", []) or []:
        category = _normalize_category(getattr(item, "category", ""))
        severity = getattr(item, "severity", 0)
        if not _has_severity(severity):
            continue
        if category in {"self_harm", "selfharm"}:
            flags.append("self_harm")
        elif category == "hate":
            flags.append("hate")
        elif category == "harassment":
            flags.append("harassment")

    return sorted(set(flags))

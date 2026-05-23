from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from config.credentials import get_azure_credential, get_key_vault_secret
from config.settings import load_auth_mode, load_safety_provider
from governance.safety import detect_safety_flags, unique_flags
from orchestration.contracts import SafetyResult
from services.content_safety import analyze_text

logger = logging.getLogger(__name__)


class SafetyGateAgent:
    def __init__(
        self,
        *,
        auth_mode: str | None = None,
        credential=None,
        key_vault_uri: str | None = None,
    ) -> None:
        self._auth_mode = auth_mode or load_auth_mode()
        self._credential = credential or get_azure_credential(self._auth_mode, async_credential=False)
        self._key_vault_uri = key_vault_uri or os.getenv("KEY_VAULT_URI", "").strip()

    def _local_content_flags(self, flags: List[str]) -> List[str]:
        return [flag for flag in flags if flag in {"self_harm", "hate", "harassment"}]

    def _content_safety_flags(self, message: str, local_flags: List[str]) -> List[str]:
        provider = load_safety_provider()
        if provider == "local":
            return self._local_content_flags(local_flags)

        endpoint = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
        api_key = os.getenv("AZURE_CONTENT_SAFETY_API_KEY", "").strip() or None

        if not api_key and self._auth_mode == "managed_identity":
            secret_name = os.getenv("KV_CONTENT_SAFETY_KEY_NAME", "").strip()
            api_key = get_key_vault_secret(
                vault_uri=self._key_vault_uri,
                credential=self._credential,
                name=secret_name,
            )

        if not endpoint:
            return self._local_content_flags(local_flags)

        flags = analyze_text(
            message,
            endpoint=endpoint,
            api_key=api_key,
            credential=self._credential,
        )
        if flags is None:
            logger.warning("Falling back to local safety heuristics.")
            return self._local_content_flags(local_flags)
        return flags

    def run(self, message: str, metadata: Dict[str, Any] | None = None) -> SafetyResult:
        metadata = metadata or {}
        flags = metadata.get("safety_flags")
        if not isinstance(flags, list):
            flags = unique_flags(detect_safety_flags(message))

        local_flags = list(flags)
        content_flags = self._content_safety_flags(message, local_flags)
        pii_flags = [flag for flag in local_flags if flag in {"contains_email", "contains_phone", "contains_url"}]
        flags = unique_flags(pii_flags + content_flags)
        redactions_required: List[str] = []
        if "contains_email" in flags or "contains_phone" in flags:
            redactions_required.append("pii")

        response_mode = "normal"
        risk_level = "low"
        if "self_harm" in flags:
            response_mode = "human_escalate"
            risk_level = "high"
        elif "hate" in flags or "harassment" in flags:
            response_mode = "refuse"
            risk_level = "high"

        deny_all = response_mode != "normal"
        tool_permissions = {
            "retrieve_docs": "deny" if deny_all else "allow",
            "search_similar_complaints": "deny" if deny_all else "allow",
            "create_ticket": "deny" if deny_all else "allow",
            "notify_team": "deny" if deny_all else "allow",
        }

        return SafetyResult(
            risk_level=risk_level,
            flags=flags,
            response_mode=response_mode,
            tool_permissions=tool_permissions,
            redactions_required=redactions_required,
        )

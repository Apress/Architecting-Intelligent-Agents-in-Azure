from __future__ import annotations

from typing import Any, Dict, List

from governance.safety import detect_safety_flags, unique_flags
from orchestration.contracts import SafetyResult


class SafetyGateAgent:
    def run(self, message: str, metadata: Dict[str, Any] | None = None) -> SafetyResult:
        metadata = metadata or {}
        flags = metadata.get("safety_flags")
        if not isinstance(flags, list):
            flags = unique_flags(detect_safety_flags(message))
        redactions_required: List[str] = []
        if "contains_email" in flags or "contains_phone" in flags:
            redactions_required.append("pii")

        tool_permissions = {
            "retrieve_docs": "allow",
            "search_similar": "allow",
            "create_ticket": "allow",
            "notify_team": "allow",
        }

        return SafetyResult(
            risk_level="low",
            flags=flags,
            response_mode="normal",
            tool_permissions=tool_permissions,
            redactions_required=redactions_required,
        )

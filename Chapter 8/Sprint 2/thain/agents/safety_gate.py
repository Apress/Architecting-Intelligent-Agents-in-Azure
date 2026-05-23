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

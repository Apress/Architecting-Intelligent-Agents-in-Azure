from __future__ import annotations

from typing import Any


_ALLOWED_FIELDS: dict[str, set[str]] = {
    "request.received": {"message_len", "has_urls", "safety_flags"},
    "policy.check": {"tool_name", "tool_kind", "decision", "matched_rule_ids", "enforced_rule_id", "reason"},
    "tool.call": {"tool_name", "args"},
    "tool.result": {"tool_name", "status", "duration_ms", "error_type", "result"},
    "approval.decision": {"approval_id", "tool_name", "approved", "timestamp", "reason"},
    "response.ready": {"category", "summary", "summary_len", "elapsed_ms"},
    "trace.emitted": {"path"},
    "error.occurred": {"error_type", "message", "stage", "tool_name"},
}


def apply_log_policy(event_type: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    allowed = _ALLOWED_FIELDS.get(event_type)
    if not allowed:
        return {}
    return {key: payload[key] for key in payload if key in allowed}

from __future__ import annotations

from typing import Any


_ALLOWED_FIELDS: dict[str, set[str]] = {
    "request.received": {"message_len", "has_urls", "safety_flags"},
    "policy.check": {"tool_name", "tool_kind", "decision", "matched_rule_ids", "enforced_rule_id", "reason"},
    "tool.call": {"tool_name", "args"},
    "tool.result": {"tool_name", "status", "duration_ms", "error_type", "result"},
    "approval.request": {
        "approval_id",
        "tool_name",
        "status",
        "requested_at",
        "expires_at",
        "approvals_group",
        "trace_id",
        "run_id",
        "turn_id",
        "tool_args_hash",
    },
    "approval.decision": {
        "approval_id",
        "tool_name",
        "approved",
        "status",
        "reason",
        "decision",
        "decided_at",
        "decision_source",
        "execution_status",
        "expires_at",
        "tool_args_hash",
    },
    "approval.status_check": {
        "approval_id",
        "status",
        "execution_status",
    },
    "response.ready": {"category", "summary", "summary_len", "elapsed_ms"},
    "llm.usage": {
        "model",
        "model_profile",
        "usage_source",
        "cache_hit",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_estimate_usd",
        "cost_estimate_available",
    },
    "dependency.retry": {
        "dependency",
        "operation",
        "attempt",
        "next_attempt",
        "max_attempts",
        "delay_ms",
    },
    "dependency.failure": {
        "dependency",
        "operation",
        "attempt",
        "max_attempts",
        "error_type",
        "retryable",
    },
    "dependency.suppressed": {
        "dependency",
        "operation",
        "cooldown_seconds",
        "consecutive_failures",
        "reason",
    },
    "fallback.used": {
        "dependency",
        "fallback_path",
        "degraded",
        "reason",
    },
    "trace.emitted": {"path"},
    "trace.appinsights": {"status", "error_type", "message"},
    "error.occurred": {"error_type", "message", "stage", "tool_name"},
}


def apply_log_policy(event_type: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    allowed = _ALLOWED_FIELDS.get(event_type)
    if not allowed:
        return {}
    return {key: payload[key] for key in payload if key in allowed}

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    description: str
    decision: str
    tool_kinds: set[str]


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    matched_rule_ids: list[str]
    enforced_rule_id: str | None
    reason: str


class PolicyEngine:
    def __init__(self, rules: Iterable[PolicyRule]) -> None:
        self._rules = list(rules)

    def evaluate(self, tool_kind: str, context: dict[str, Any]) -> PolicyDecision:
        deny_ids: list[str] = []
        warn_ids: list[str] = []
        matched_ids: list[str] = []

        approvals_enabled = bool(context.get("approvals_enabled", False))
        policy_requires_approval = bool(context.get("policy_requires_approval", True))
        search_mode = str(context.get("search_mode", "off"))
        safety_flags = set(context.get("safety_flags", []))
        pii_write_block = bool(context.get("pii_write_block", False))
        write_calls_in_turn = int(context.get("write_calls_in_turn", 0))
        warn_write_threshold = int(context.get("warn_write_threshold", 2))
        retrieval_attempted = bool(context.get("retrieval_attempted", False))
        retrieval_results_count = context.get("retrieval_results_count")

        is_write_kind = tool_kind in {"write", "ticket", "notify"}

        if is_write_kind and policy_requires_approval and not approvals_enabled:
            deny_ids.append("POL-DENY-001")

        if tool_kind == "retrieve" and search_mode != "agentic":
            deny_ids.append("POL-DENY-002")

        if is_write_kind and pii_write_block and (
            "contains_email" in safety_flags or "contains_phone" in safety_flags
        ):
            deny_ids.append("POL-DENY-004")

        if is_write_kind and write_calls_in_turn >= warn_write_threshold:
            warn_ids.append("POL-WARN-001")

        if is_write_kind and retrieval_attempted and retrieval_results_count == 0:
            warn_ids.append("POL-WARN-002")

        matched_ids.extend(deny_ids)
        matched_ids.extend(warn_ids)

        for rule in self._rules:
            if tool_kind not in rule.tool_kinds:
                continue
            matched_ids.append(rule.rule_id)
            if rule.decision == "deny":
                deny_ids.append(rule.rule_id)
            elif rule.decision == "warn":
                warn_ids.append(rule.rule_id)

        if deny_ids:
            return PolicyDecision("deny", matched_ids, deny_ids[0], "policy_denied")
        if warn_ids:
            return PolicyDecision("warn", matched_ids, warn_ids[0], "policy_warn")
        return PolicyDecision("allow", matched_ids, None, "policy_allow")


def default_policy_rules(approvals_enabled: bool) -> list[PolicyRule]:
    _ = approvals_enabled
    return []

from __future__ import annotations

from orchestration.contracts import SafetyResult, TriageResult


def should_run_recall(triage: TriageResult, safety: SafetyResult) -> bool:
    if safety.tool_permissions.get("search_similar_complaints") != "allow":
        return False
    return triage.needs_retrieval and safety.response_mode == "normal"


def should_run_docs(triage: TriageResult, safety: SafetyResult) -> bool:
    if safety.tool_permissions.get("retrieve_docs") != "allow":
        return False
    return triage.needs_docs and safety.response_mode == "normal"


def should_run_action(triage: TriageResult, safety: SafetyResult) -> bool:
    if safety.response_mode != "normal":
        return False
    if triage.action_candidate == "ticket":
        return safety.tool_permissions.get("create_ticket") == "allow"
    if triage.action_candidate == "notify":
        return safety.tool_permissions.get("notify_team") == "allow"
    if triage.action_candidate == "both":
        return (
            safety.tool_permissions.get("create_ticket") == "allow"
            or safety.tool_permissions.get("notify_team") == "allow"
        )
    return False

from __future__ import annotations

from orchestration.contracts import SafetyResult, TriageResult


def should_run_recall(triage: TriageResult, safety: SafetyResult) -> bool:
    if safety.tool_permissions.get("search_similar") != "allow":
        return False
    return triage.needs_retrieval and safety.response_mode == "normal"


def should_run_docs(triage: TriageResult, safety: SafetyResult) -> bool:
    if safety.tool_permissions.get("retrieve_docs") != "allow":
        return False
    return triage.needs_docs and safety.response_mode == "normal"


def should_run_action(triage: TriageResult, safety: SafetyResult) -> bool:
    return triage.action_candidate != "none" and safety.response_mode == "normal"

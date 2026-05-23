from __future__ import annotations

from typing import List

from tools.classifier import classify_issue
from orchestration.contracts import TriageResult


_HIGH_URGENCY = (
    "evacuation",
    "shutdown",
    "fire",
    "hazard",
    "injury",
    "explosion",
    "safety",
    "critical",
    "urgent",
)
_MEDIUM_URGENCY = (
    "refund",
    "delay",
    "outage",
    "disconnect",
    "failure",
    "issue",
    "broken",
)

_RETRIEVAL_HINTS = (
    "similar",
    "again",
    "recurring",
    "previous",
    "before",
    "recent",
    "other customers",
    "else",
)

_DOC_HINTS = (
    "procedure",
    "sop",
    "playbook",
    "policy",
    "steps",
    "guide",
    "what should we do",
    "standard procedure",
)


class TriageAgent:
    def run(self, message: str) -> TriageResult:
        lowered = message.lower()
        category = classify_issue(message).get("category", "General Inquiry")

        urgency = "low"
        if any(term in lowered for term in _HIGH_URGENCY):
            urgency = "high"
        elif any(term in lowered for term in _MEDIUM_URGENCY):
            urgency = "medium"

        needs_retrieval = any(term in lowered for term in _RETRIEVAL_HINTS)
        needs_docs = any(term in lowered for term in _DOC_HINTS)

        wants_ticket = any(term in lowered for term in ("ticket", "case", "incident", "escalate"))
        wants_notify = any(term in lowered for term in ("notify", "alert", "inform team"))
        action_candidate = "none"
        if wants_ticket and wants_notify:
            action_candidate = "both"
        elif wants_ticket:
            action_candidate = "ticket"
        elif wants_notify:
            action_candidate = "notify"

        missing_info: List[str] = []
        if "refund" in lowered or "payment" in lowered:
            missing_info.extend(["transaction_id", "transaction_date"])
        if len(message.strip()) < 20:
            missing_info.append("more_details")

        return TriageResult(
            category=str(category),
            urgency=urgency,
            needs_retrieval=needs_retrieval,
            needs_docs=needs_docs,
            action_candidate=action_candidate,
            missing_info=missing_info,
        )

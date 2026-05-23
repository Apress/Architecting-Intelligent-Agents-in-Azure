from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List

from agent_framework import Agent

from tools.classifier import classify_issue
from orchestration.contracts import TriageResult


_ALLOWED_URGENCY = {"low", "medium", "high"}
_ALLOWED_ACTIONS = {"none", "ticket", "notify", "both"}

_HIGH_URGENCY = ("evacuation", "shutdown", "fire", "hazard", "injury", "explosion", "safety", "critical", "urgent")
_MEDIUM_URGENCY = ("refund", "delay", "outage", "disconnect", "failure", "issue", "broken")

_RETRIEVAL_HINTS = ("similar", "again", "recurring", "previous", "before", "recent", "other customers", "else")
_DOC_HINTS = ("procedure", "sop", "playbook", "policy", "steps", "guide", "what should we do", "standard procedure")


class DeterministicTriageAgent:
    async def run(self, message: str, metadata: Dict[str, Any] | None = None) -> TriageResult:
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

        return validate_triage_result(
            TriageResult(
                category=str(category),
                urgency=urgency,
                needs_retrieval=needs_retrieval,
                needs_docs=needs_docs,
                action_candidate=action_candidate,
                missing_info=missing_info,
            )
        )


class AgenticTriageAgent:
    def __init__(self, chat_client: Any) -> None:
        self._chat_client = chat_client

    async def run(self, message: str, metadata: Dict[str, Any] | None = None) -> TriageResult:
        instructions = (
            "You are a triage classifier. Return ONLY JSON with keys: "
            "category, urgency, needs_retrieval, needs_docs, action_candidate, missing_info. "
            "urgency must be one of low|medium|high. "
            "action_candidate must be one of none|ticket|notify|both. "
            "missing_info must be a JSON array of short strings."
        )
        agent = Agent(
            client=self._chat_client,
            name="TriageAgent",
            instructions=instructions,
            tools=[],
            default_options={"mode": "none"},
        )
        response = await agent.run(message)

        raw = response.text if response.text else ""
        payload = _parse_triage_payload(raw)
        candidate = TriageResult(
            category=str(payload.get("category", "General Inquiry")),
            urgency=str(payload.get("urgency", "low")),
            needs_retrieval=bool(payload.get("needs_retrieval", False)),
            needs_docs=bool(payload.get("needs_docs", False)),
            action_candidate=str(payload.get("action_candidate", "none")),
            missing_info=list(payload.get("missing_info", [])),
        )
        return validate_triage_result(candidate)


def select_triage_agent(mode: str, chat_client: Any | None = None) -> Any:
    if mode == "agentic":
        if chat_client is None:
            raise RuntimeError("Agentic triage requires a chat client.")
        return AgenticTriageAgent(chat_client)
    return DeterministicTriageAgent()


def validate_triage_result(result: TriageResult) -> TriageResult:
    urgency = result.urgency if result.urgency in _ALLOWED_URGENCY else "low"
    action_candidate = result.action_candidate if result.action_candidate in _ALLOWED_ACTIONS else "none"
    missing_info = [str(item) for item in result.missing_info if str(item).strip()]

    return TriageResult(
        category=result.category or "General Inquiry",
        urgency=urgency,
        needs_retrieval=bool(result.needs_retrieval),
        needs_docs=bool(result.needs_docs),
        action_candidate=action_candidate,
        missing_info=missing_info,
    )


def _parse_triage_payload(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        segments = cleaned.split("```")
        cleaned = segments[1] if len(segments) > 1 else cleaned
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
        cleaned = cleaned.strip()

    candidates = [cleaned]
    if "{" in cleaned and "}" in cleaned:
        first = cleaned.find("{")
        last = cleaned.rfind("}") + 1
        if last > first:
            candidates.append(cleaned[first:last])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def triage_summary(triage: TriageResult) -> Dict[str, Any]:
    return asdict(triage)

from __future__ import annotations

import hashlib
import logging
from typing import Annotated, Any, Dict

from agent_framework import tool
from services.approvals import ApprovalService, requires_approval

logger = logging.getLogger(__name__)


TOOL_REGISTRY = {
    "create_ticket": "write",
    "notify_team": "write",
    "retrieve_docs": "read",
}



def _stable_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}-{digest}"


def _clip_items(items: list[str] | None, limit: int = 3) -> list[str]:
    if not items:
        return []
    return list(items)[:limit]


def create_action_tools(action_config, approval_service: ApprovalService | None = None) -> list[Any]:
    tools: list[Any] = []

    if action_config.enable_tickets:

        @tool(
            name="create_ticket",
            description="Create an incident ticket for follow-up.",
        )
        async def create_ticket(
            summary: Annotated[str, "Short ticket summary."],
            severity: Annotated[str, "Severity label (e.g., low, medium, high, critical)."],
            customer_id: Annotated[str, "Customer or tenant identifier."],
            evidence_summary: Annotated[str, "Short evidence summary used to justify the ticket."],
            evidence_items: Annotated[list[str] | None, "Up to three short evidence bullet points."] = None,
        ) -> Dict[str, Any]:
            if approval_service and requires_approval(TOOL_REGISTRY["create_ticket"], approval_service.enabled):
                approved = await approval_service.request_approval(
                    "create_ticket",
                    {
                        "summary": summary,
                        "severity": severity,
                        "customer_id": customer_id,
                        "evidence_summary": evidence_summary,
                        "evidence_items": _clip_items(evidence_items),
                    },
                )
                if not approved:
                    return {"status": "denied", "approved": False, "reason": "approval_not_provided"}

            ticket_id = _stable_id("TCK", f"{customer_id}:{summary}")
            result = {
                "ticket_id": ticket_id,
                "status": "created",
                "approved": True,
                "url": f"https://tickets.thain.local/{ticket_id}",
                "summary": summary,
                "severity": severity,
                "evidence_summary": evidence_summary,
                "evidence_items": _clip_items(evidence_items),
            }
            logger.info("Ticket stub created: %s", ticket_id)
            return result

        tools.append(create_ticket)

    if action_config.enable_notifications:

        @tool(
            name="notify_team",
            description="Send a notification to a team or channel.",
        )
        async def notify_team(
            channel: Annotated[str, "Target channel or team."],
            message: Annotated[str, "Notification message."],
            priority: Annotated[str, "Priority label (e.g., low, medium, high)."],
            related_ticket_id: Annotated[str | None, "Optional related ticket ID."] = None,
        ) -> Dict[str, Any]:
            if approval_service and requires_approval(TOOL_REGISTRY["notify_team"], approval_service.enabled):
                approved = await approval_service.request_approval(
                    "notify_team",
                    {
                        "channel": channel,
                        "message": message,
                        "priority": priority,
                        "related_ticket_id": related_ticket_id,
                    },
                )
                if not approved:
                    return {"status": "denied", "approved": False, "reason": "approval_not_provided"}

            seed = f"{channel}:{message}:{related_ticket_id or ''}"
            message_id = _stable_id("MSG", seed)
            result = {
                "message_id": message_id,
                "status": "sent",
                "approved": True,
                "channel": channel,
                "priority": priority,
                "related_ticket_id": related_ticket_id,
            }
            logger.info("Notification stub sent: %s", message_id)
            return result

        tools.append(notify_team)

    if action_config.enable_docs:

        @tool(
            name="retrieve_docs",
            description="Retrieve relevant knowledge-base documents for a query.",
        )
        async def retrieve_docs(
            query: Annotated[str, "Search query for documents."],
            top_k: Annotated[int, "Maximum number of documents to return."] = 3,
            tags: Annotated[list[str] | None, "Optional tag filters."] = None,
        ) -> list[dict[str, Any]]:
            corpus = [
                {
                    "title": "Equipment shutdown response checklist",
                    "snippet": "Steps to follow after an unexpected shutdown and evacuation.",
                    "url": "https://kb.thain.local/shutdown-checklist",
                    "source": "kb",
                    "tags": ["shutdown", "safety", "evacuation"],
                },
                {
                    "title": "Recurring incident escalation playbook",
                    "snippet": "When to open tickets and notify safety teams for repeat incidents.",
                    "url": "https://kb.thain.local/escalation-playbook",
                    "source": "kb",
                    "tags": ["escalation", "incident"],
                },
                {
                    "title": "Sensor calibration troubleshooting",
                    "snippet": "Diagnosing sensor faults that lead to operational disruptions.",
                    "url": "https://kb.thain.local/sensor-calibration",
                    "source": "kb",
                    "tags": ["sensor", "hardware"],
                },
            ]

            query_lower = query.lower()
            matches = [
                doc
                for doc in corpus
                if query_lower in doc["title"].lower() or query_lower in doc["snippet"].lower()
            ]

            if tags:
                tag_set = {tag.lower() for tag in tags}
                matches = [
                    doc
                    for doc in matches
                    if tag_set.intersection({tag.lower() for tag in doc.get("tags", [])})
                ]

            limit = max(1, top_k) if top_k else 3
            results = list(matches)
            if len(results) < limit:
                for doc in corpus:
                    if doc not in results:
                        results.append(doc)
                        if len(results) >= limit:
                            break
            return results[:limit]

        tools.append(retrieve_docs)

    return tools










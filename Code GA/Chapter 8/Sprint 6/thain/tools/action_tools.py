from __future__ import annotations

import hashlib
import logging
from typing import Annotated, Any, Dict

from agent_framework import tool
from services.approvals import ApprovalOutcome, ApprovalService, requires_approval

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


def _execute_ticket_action(
    payload: dict[str, Any],
    approval_id: str | None = None,
) -> Dict[str, Any]:
    summary = str(payload.get("summary") or "")
    severity = str(payload.get("severity") or "low")
    customer_id = str(payload.get("customer_id") or "unknown")
    evidence_summary = str(payload.get("evidence_summary") or "")
    evidence_items = _clip_items(payload.get("evidence_items"))
    ticket_id = _stable_id("TCK", f"{customer_id}:{summary}")
    result: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "status": "created",
        "approved": True,
        "url": f"https://tickets.thain.local/{ticket_id}",
        "summary": summary,
        "severity": severity,
        "evidence_summary": evidence_summary,
        "evidence_items": evidence_items,
    }
    if approval_id:
        result["approval_id"] = approval_id
    logger.info("Ticket stub created: %s", ticket_id)
    return result


def _execute_notify_action(
    payload: dict[str, Any],
    approval_id: str | None = None,
) -> Dict[str, Any]:
    channel = str(payload.get("channel") or "support-triage")
    message = str(payload.get("message") or "")
    priority = str(payload.get("priority") or "low")
    related_ticket_id = payload.get("related_ticket_id")
    seed = f"{channel}:{message}:{related_ticket_id or ''}"
    message_id = _stable_id("MSG", seed)
    result: Dict[str, Any] = {
        "message_id": message_id,
        "status": "sent",
        "approved": True,
        "channel": channel,
        "priority": priority,
        "related_ticket_id": related_ticket_id,
    }
    if approval_id:
        result["approval_id"] = approval_id
    logger.info("Notification stub sent: %s", message_id)
    return result


def execute_approved_action(
    tool_name: str,
    payload: dict[str, Any],
    approval_id: str | None = None,
) -> Dict[str, Any]:
    if tool_name == "create_ticket":
        return _execute_ticket_action(payload, approval_id=approval_id)
    if tool_name == "notify_team":
        return _execute_notify_action(payload, approval_id=approval_id)
    raise ValueError(f"Unsupported approval tool: {tool_name}")


def create_action_tools(
    action_config,
    approval_service: ApprovalService | None = None,
    docs_service: Any | None = None,
) -> list[Any]:
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
            approval_outcome: ApprovalOutcome | None = None
            if approval_service and requires_approval(TOOL_REGISTRY["create_ticket"], approval_service.enabled):
                approval_payload = {
                    "summary": summary,
                    "severity": severity,
                    "customer_id": customer_id,
                    "evidence_summary": evidence_summary,
                    "evidence_items": _clip_items(evidence_items),
                }
                approval_outcome = await approval_service.request_approval(
                    "create_ticket",
                    approval_payload,
                )
                if not approval_outcome.approved:
                    reason = "approval_not_provided"
                    if approval_outcome.status == "pending":
                        reason = "approval_pending"
                    elif approval_outcome.status == "expired":
                        reason = "approval_expired"
                    elif approval_outcome.status == "denied":
                        reason = "approval_denied"
                    return {
                        "status": approval_outcome.status,
                        "approved": False,
                        "reason": reason,
                        "approval_id": approval_outcome.approval_id,
                        "expires_at": approval_outcome.expires_at,
                    }

                if not await approval_service.try_mark_executed(approval_outcome.approval_id):
                    return {
                        "status": "denied",
                        "approved": False,
                        "reason": "approval_already_executed",
                        "approval_id": approval_outcome.approval_id,
                    }

            payload = {
                "summary": summary,
                "severity": severity,
                "customer_id": customer_id,
                "evidence_summary": evidence_summary,
                "evidence_items": _clip_items(evidence_items),
            }
            return _execute_ticket_action(
                payload,
                approval_id=approval_outcome.approval_id if approval_outcome else None,
            )

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
            approval_outcome: ApprovalOutcome | None = None
            if approval_service and requires_approval(TOOL_REGISTRY["notify_team"], approval_service.enabled):
                approval_payload = {
                    "channel": channel,
                    "message": message,
                    "priority": priority,
                    "related_ticket_id": related_ticket_id,
                }
                approval_outcome = await approval_service.request_approval(
                    "notify_team",
                    approval_payload,
                )
                if not approval_outcome.approved:
                    reason = "approval_not_provided"
                    if approval_outcome.status == "pending":
                        reason = "approval_pending"
                    elif approval_outcome.status == "expired":
                        reason = "approval_expired"
                    elif approval_outcome.status == "denied":
                        reason = "approval_denied"
                    return {
                        "status": approval_outcome.status,
                        "approved": False,
                        "reason": reason,
                        "approval_id": approval_outcome.approval_id,
                        "expires_at": approval_outcome.expires_at,
                    }

                if not await approval_service.try_mark_executed(approval_outcome.approval_id):
                    return {
                        "status": "denied",
                        "approved": False,
                        "reason": "approval_already_executed",
                        "approval_id": approval_outcome.approval_id,
                    }

            payload = {
                "channel": channel,
                "message": message,
                "priority": priority,
                "related_ticket_id": related_ticket_id,
            }
            return _execute_notify_action(
                payload,
                approval_id=approval_outcome.approval_id if approval_outcome else None,
            )

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
            if not docs_service:
                logger.warning("retrieve_docs called, but docs service is not configured.")
                return [{"_trace_error": {"error_type": "DocsConfigError", "reason": "docs_service_unavailable"}}]

            limit = max(1, top_k) if top_k else 3
            try:
                return await docs_service.retrieve(query=query, top_k=limit, tags=tags)
            except Exception as exc:
                logger.warning("retrieve_docs failed: %s", exc, exc_info=True)
                return [{"_trace_error": {"error_type": type(exc).__name__, "reason": "docs_retrieval_failed"}}]

        tools.append(retrieve_docs)

    return tools










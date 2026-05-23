from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from governance.safety import redact_pii
from orchestration.contracts import ActionResult, Blackboard


class ActionAgent:
    def __init__(
        self,
        tools: Dict[str, Any],
        *,
        customer_id: str,
        approvals_enabled: bool = False,
    ) -> None:
        self._tools = tools
        self._customer_id = customer_id
        self._approvals_enabled = approvals_enabled

    async def run(self, board: Blackboard) -> ActionResult:
        actions: List[Dict[str, Any]] = []
        ticket_result: Dict[str, Any] | None = None
        notify_result: Dict[str, Any] | None = None

        if not board.triage:
            return ActionResult(actions=actions)

        candidate = board.triage.action_candidate
        if candidate == "none":
            actions.append(
                _action_record(
                    action_type="none",
                    status="skipped",
                    reason="no_candidate",
                    approval_required=self._approvals_enabled,
                )
            )
            return ActionResult(actions=actions)

        action_plan: list[str] = []
        if candidate in {"ticket", "both"}:
            action_plan.append("ticket")
        if candidate in {"notify", "both"}:
            action_plan.append("notify")

        seen_action_ids: set[str] = set()
        for action_type in action_plan:
            action_id = _action_id(board.turn_id, action_type)
            if action_id in seen_action_ids:
                actions.append(
                    _action_record(
                        action_type=action_type,
                        status="skipped",
                        reason="duplicate",
                        approval_required=self._approvals_enabled,
                        action_id=action_id,
                    )
                )
                continue
            seen_action_ids.add(action_id)

            permission_key = "create_ticket" if action_type == "ticket" else "notify_team"
            if board.safety and board.safety.tool_permissions.get(permission_key) != "allow":
                actions.append(
                    _action_record(
                        action_type=action_type,
                        status="denied",
                        reason="safety",
                        approval_required=self._approvals_enabled,
                        action_id=action_id,
                    )
                )
                continue

            tool = self._tools.get(permission_key)
            if tool is None:
                actions.append(
                    _action_record(
                        action_type=action_type,
                        status="skipped",
                        reason="missing_tool",
                        approval_required=self._approvals_enabled,
                        action_id=action_id,
                    )
                )
                continue

            try:
                if action_type == "ticket":
                    ticket_result = await _run_ticket_tool(
                        tool,
                        board,
                        customer_id=self._customer_id,
                    )
                    status, reason = _status_from_tool_result(ticket_result)
                    approval_id = ticket_result.get("approval_id") if isinstance(ticket_result, dict) else None
                    actions.append(
                        _action_record(
                            action_type=action_type,
                            status=status,
                            reason=reason,
                            approval_required=self._approvals_enabled,
                            tool_name="create_ticket",
                            action_id=action_id,
                            approval_id=approval_id,
                        )
                    )
                else:
                    notify_result = await _run_notify_tool(
                        tool,
                        board,
                        ticket_result=ticket_result,
                    )
                    status, reason = _status_from_tool_result(notify_result)
                    approval_id = notify_result.get("approval_id") if isinstance(notify_result, dict) else None
                    actions.append(
                        _action_record(
                            action_type=action_type,
                            status=status,
                            reason=reason,
                            approval_required=self._approvals_enabled,
                            tool_name="notify_team",
                            action_id=action_id,
                            approval_id=approval_id,
                        )
                    )
            except Exception as exc:
                actions.append(
                    _action_record(
                        action_type=action_type,
                        status="failed",
                        reason="tool_error",
                        approval_required=self._approvals_enabled,
                        tool_name=permission_key,
                        action_id=action_id,
                        message=str(exc) or type(exc).__name__,
                    )
                )

        return ActionResult(actions=actions, ticket=ticket_result, notification=notify_result)


def _action_id(turn_id: str, action_type: str) -> str:
    return f"{turn_id}:{action_type}"


def _action_record(
    *,
    action_type: str,
    status: str,
    reason: str,
    approval_required: bool,
    tool_name: str | None = None,
    action_id: str | None = None,
    approval_id: str | None = None,
    message: str | None = None,
) -> Dict[str, Any]:
    record = {
        "action_type": action_type,
        "status": status,
        "reason": reason,
        "approval_required": approval_required,
        "tool_name": tool_name,
        "action_id": action_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if approval_id:
        record["approval_id"] = approval_id
    if message:
        record["message"] = message
    return record


def _status_from_tool_result(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return ("failed", "tool_error")
    if result.get("status") == "pending":
        return ("pending", "approval_pending")
    if result.get("status") in {"failed", "error"}:
        return ("failed", "tool_error")
    if result.get("status") == "denied" or result.get("approved") is False:
        reason = result.get("reason") or "approval"
        if reason == "policy_denied":
            return ("denied", "policy")
        if reason in {"approval_not_provided", "approval_pending", "approval_expired", "approval_denied"}:
            return ("denied", "approval")
        return ("denied", "tool_denied")
    if result.get("status") in {"created", "sent"} or result.get("approved") is True:
        return ("executed", "tool_ok")
    return ("failed", "tool_error")


def _collect_evidence(board: Blackboard) -> tuple[str, list[str]]:
    items: list[str] = []
    if board.recall and board.recall.matches:
        for match in board.recall.matches:
            summary = match.get("summary")
            if summary:
                items.append(str(summary))
    if board.knowledge and board.knowledge.docs:
        for doc in board.knowledge.docs:
            title = doc.get("title")
            if title:
                items.append(str(title))
    items = items[:3]
    if items:
        summary = f"Evidence gathered: {len(items)} item(s) referenced."
    else:
        summary = "No supporting evidence retrieved."
    return summary, items


def _redact_if_needed(board: Blackboard, value: str) -> str:
    if board.safety and "pii" in board.safety.redactions_required:
        return redact_pii(value)
    return value


def _redact_items_if_needed(board: Blackboard, items: list[str]) -> list[str]:
    if board.safety and "pii" in board.safety.redactions_required:
        return [redact_pii(item) for item in items]
    return items


async def _run_ticket_tool(tool: Any, board: Blackboard, customer_id: str) -> Dict[str, Any]:
    message = board.message.get("text", "")
    category = board.triage.category if board.triage else "General Inquiry"
    urgency = board.triage.urgency if board.triage else "low"
    summary = _redact_if_needed(board, f"{category} issue reported: {message[:120]}")
    evidence_summary, evidence_items = _collect_evidence(board)
    evidence_summary = _redact_if_needed(board, evidence_summary)
    evidence_items = _redact_items_if_needed(board, evidence_items)

    return await tool(
        summary=summary,
        severity=urgency,
        customer_id=customer_id,
        evidence_summary=evidence_summary,
        evidence_items=evidence_items,
    )


async def _run_notify_tool(
    tool: Any,
    board: Blackboard,
    ticket_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    category = board.triage.category if board.triage else "General Inquiry"
    urgency = board.triage.urgency if board.triage else "low"
    evidence_summary, _ = _collect_evidence(board)
    message = f"Triage alert: {category} ({urgency}). {evidence_summary}"
    message = _redact_if_needed(board, message)
    related_ticket_id = None
    if isinstance(ticket_result, dict):
        related_ticket_id = ticket_result.get("ticket_id")

    return await tool(
        channel="support-triage",
        message=message,
        priority=urgency,
        related_ticket_id=related_ticket_id,
    )

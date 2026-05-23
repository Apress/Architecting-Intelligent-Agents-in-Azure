from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from agents.action_agent import ActionAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.recall_agent import RecallAgent
from agents.safety_gate import SafetyGateAgent
from orchestration.blackboard import record_failure
from orchestration.contracts import (
    Blackboard,
    NormalizedResponse,
    ResponsePolicy,
    STAGE_KNOWLEDGE,
    STAGE_RECALL,
    STAGE_SAFETY,
    STAGE_TRIAGE,
    STAGE_ACTION,
)
from orchestration.routing import should_run_action, should_run_docs, should_run_recall
from governance.safety import redact_pii_payload


class Orchestrator:
    def __init__(
        self,
        safety_gate: SafetyGateAgent,
        triage_agent: Any,
        recall_agent: RecallAgent | None,
        knowledge_agent: KnowledgeAgent | None,
        action_agent: ActionAgent | None,
    ) -> None:
        self._safety_gate = safety_gate
        self._triage_agent = triage_agent
        self._recall_agent = recall_agent
        self._knowledge_agent = knowledge_agent
        self._action_agent = action_agent

    async def run_turn(self, message: str, turn_id: str, metadata: Dict[str, Any]) -> Blackboard:
        board = Blackboard(turn_id=turn_id, message={"text": message, "metadata": metadata})

        try:
            board.safety = self._safety_gate.run(message, metadata)
        except Exception as exc:  # pragma: no cover - defensive
            record_failure(board, STAGE_SAFETY, type(exc).__name__, str(exc))

        if board.safety and board.safety.response_mode in {"refuse", "human_escalate"}:
            return board

        try:
            board.triage = await self._triage_agent.run(message, metadata)
        except Exception as exc:  # pragma: no cover - defensive
            record_failure(board, STAGE_TRIAGE, type(exc).__name__, str(exc))
            return board

        if board.safety and board.triage:
            if should_run_recall(board.triage, board.safety) and self._recall_agent:
                try:
                    board.recall = await self._recall_agent.run(message, board.triage.category)
                except Exception as exc:
                    record_failure(board, STAGE_RECALL, type(exc).__name__, str(exc))

            if should_run_docs(board.triage, board.safety) and self._knowledge_agent:
                try:
                    board.knowledge = await self._knowledge_agent.run(message)
                except Exception as exc:
                    record_failure(board, STAGE_KNOWLEDGE, type(exc).__name__, str(exc))

            if should_run_action(board.triage, board.safety) and self._action_agent:
                try:
                    board.action = await self._action_agent.run(board)
                except Exception as exc:
                    record_failure(board, STAGE_ACTION, type(exc).__name__, str(exc))

        return board

    @staticmethod
    def build_triage_context(board: Blackboard) -> str:
        if not board.triage:
            return ""
        triage = asdict(board.triage)
        missing_info = triage.get("missing_info", [])
        return (
            "Triage context:\n"
            f"- category: {triage.get('category')}\n"
            f"- urgency: {triage.get('urgency')}\n"
            f"- needs_retrieval: {triage.get('needs_retrieval')}\n"
            f"- needs_docs: {triage.get('needs_docs')}\n"
            f"- action_candidate: {triage.get('action_candidate')}\n"
            f"- missing_info: {missing_info}\n"
        )

    @staticmethod
    def build_recall_context(board: Blackboard) -> str:
        if not board.recall:
            return ""
        recall = asdict(board.recall)
        if board.safety and "pii" in board.safety.redactions_required:
            recall = redact_pii_payload(recall)
        return (
            "Recall context:\n"
            f"- retrieval_mode: {recall.get('retrieval_mode')}\n"
            f"- recency: {recall.get('recency')}\n"
            f"- matches: {recall.get('matches', [])}\n"
        )

    @staticmethod
    def build_knowledge_context(board: Blackboard) -> str:
        if not board.knowledge:
            return ""
        knowledge = asdict(board.knowledge)
        if board.safety and "pii" in board.safety.redactions_required:
            knowledge = redact_pii_payload(knowledge)
        return "Knowledge context:\n" f"- docs: {knowledge.get('docs', [])}\n"

    @staticmethod
    def build_action_context(board: Blackboard) -> str:
        if not board.action:
            return ""
        actions = asdict(board.action)
        if board.safety and "pii" in board.safety.redactions_required:
            actions = redact_pii_payload(actions)
        return "Action context:\n" f"- actions: {actions.get('actions', [])}\n"

    @staticmethod
    def build_response_policy(board: Blackboard) -> ResponsePolicy:
        response_mode = board.safety.response_mode if board.safety else "normal"
        actions = board.action.actions if board.action else []
        action_status = "none"
        notes: list[str] = []

        if response_mode != "normal":
            action_status = "suppressed"
            notes.append(
                f"Response mode is {response_mode}. Do not call tools; provide a safety response."
            )
        else:
            if actions:
                has_denied = any(action.get("status") == "denied" for action in actions)
                has_failed = any(action.get("status") == "failed" for action in actions)
                has_executed = any(action.get("status") == "executed" for action in actions)
                has_pending = any(action.get("status") == "pending" for action in actions)
                if has_denied:
                    action_status = "denied"
                    notes.append(
                        "At least one action was denied. State that the action was not performed."
                    )
                if has_failed:
                    action_status = "failed" if not has_denied else action_status
                    notes.append("An action failed. State that the action could not be completed.")
                if has_executed:
                    action_status = "executed" if not has_denied and not has_failed else action_status
                    notes.append("At least one action was executed. Confirm the action occurred.")
                if has_pending:
                    action_status = "pending" if not has_denied and not has_failed else action_status
                    notes.append(
                        "At least one action is pending approval. Provide the approval ID and next steps."
                    )
            else:
                notes.append("No actions were taken.")

        return ResponsePolicy(
            response_mode=response_mode,
            action_status=action_status,
            enforcement_notes=notes,
        )

    @classmethod
    def build_context_block(cls, board: Blackboard) -> str:
        policy = cls.build_response_policy(board)
        policy_context = (
            "Response policy:\n"
            f"- response_mode: {policy.response_mode}\n"
            f"- action_status: {policy.action_status}\n"
            f"- enforcement_notes: {policy.enforcement_notes}\n"
        )
        parts = [
            cls.build_triage_context(board),
            cls.build_recall_context(board),
            cls.build_knowledge_context(board),
            cls.build_action_context(board),
            policy_context,
        ]
        return "".join(part for part in parts if part)

    @staticmethod
    def build_response(board: Blackboard, summary: str, trace_id: str | None = None) -> NormalizedResponse:
        response_mode = "normal"
        if board.safety:
            response_mode = board.safety.response_mode
        category = board.triage.category if board.triage else "General Inquiry"
        return NormalizedResponse(
            response_mode=response_mode,
            category=category,
            summary=summary,
            trace_id=trace_id,
        )

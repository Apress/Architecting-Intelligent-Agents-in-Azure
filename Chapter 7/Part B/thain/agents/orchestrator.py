from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from agents.knowledge_agent import KnowledgeAgent
from agents.recall_agent import RecallAgent
from agents.safety_gate import SafetyGateAgent
from orchestration.blackboard import record_failure
from orchestration.contracts import (
    Blackboard,
    NormalizedResponse,
    STAGE_KNOWLEDGE,
    STAGE_RECALL,
    STAGE_SAFETY,
    STAGE_TRIAGE,
)
from orchestration.routing import should_run_docs, should_run_recall


class Orchestrator:
    def __init__(
        self,
        safety_gate: SafetyGateAgent,
        triage_agent: Any,
        recall_agent: RecallAgent | None,
        knowledge_agent: KnowledgeAgent | None,
    ) -> None:
        self._safety_gate = safety_gate
        self._triage_agent = triage_agent
        self._recall_agent = recall_agent
        self._knowledge_agent = knowledge_agent

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
        return "Knowledge context:\n" f"- docs: {knowledge.get('docs', [])}\n"

    @classmethod
    def build_context_block(cls, board: Blackboard) -> str:
        parts = [
            cls.build_triage_context(board),
            cls.build_recall_context(board),
            cls.build_knowledge_context(board),
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

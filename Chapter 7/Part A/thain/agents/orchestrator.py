from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from agents.safety_gate import SafetyGateAgent
from agents.triage_agent import TriageAgent
from orchestration.blackboard import record_failure
from orchestration.contracts import (
    Blackboard,
    NormalizedResponse,
    STAGE_SAFETY,
    STAGE_TRIAGE,
)


class Orchestrator:
    def __init__(self, safety_gate: SafetyGateAgent, triage_agent: TriageAgent) -> None:
        self._safety_gate = safety_gate
        self._triage_agent = triage_agent

    def run_turn(self, message: str, turn_id: str, metadata: Dict[str, Any]) -> Blackboard:
        board = Blackboard(turn_id=turn_id, message={"text": message, "metadata": metadata})

        try:
            board.safety = self._safety_gate.run(message, metadata)
        except Exception as exc:  # pragma: no cover - defensive
            record_failure(board, STAGE_SAFETY, type(exc).__name__, str(exc))

        if board.safety and board.safety.response_mode in {"refuse", "human_escalate"}:
            return board

        try:
            board.triage = self._triage_agent.run(message)
        except Exception as exc:  # pragma: no cover - defensive
            record_failure(board, STAGE_TRIAGE, type(exc).__name__, str(exc))

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

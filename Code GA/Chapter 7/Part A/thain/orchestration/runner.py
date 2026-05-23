from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from agents.orchestrator import Orchestrator
from agents.safety_gate import SafetyGateAgent
from agents.triage_agent import TriageAgent
from orchestration.blackboard import build_message_metadata
from orchestration.contracts import Blackboard, NormalizedResponse


class OrchestratorRunner:
    def __init__(self) -> None:
        self._orchestrator = Orchestrator(SafetyGateAgent(), TriageAgent())

    def run(self, message: str, turn_id: str, metadata: Dict[str, Any]) -> Blackboard:
        return self._orchestrator.run_turn(message, turn_id, metadata)

    def triage_context(self, board: Blackboard) -> str:
        return self._orchestrator.build_triage_context(board)

    def build_response(self, board: Blackboard, summary: str, trace_id: str | None = None) -> NormalizedResponse:
        return self._orchestrator.build_response(board, summary, trace_id)


def safe_board_snapshot(board: Blackboard) -> Dict[str, Any]:
    return asdict(board)

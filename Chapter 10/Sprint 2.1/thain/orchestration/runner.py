from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from agents.action_agent import ActionAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.orchestrator import Orchestrator
from agents.recall_agent import RecallAgent
from agents.safety_gate import SafetyGateAgent
from agents.triage_agent import select_triage_agent
from config.settings import MultiAgentConfig
from orchestration.blackboard import blackboard_to_dict, build_message_metadata
from orchestration.contracts import Blackboard


class OrchestratorRunner:
    def __init__(
        self,
        config: MultiAgentConfig,
        chat_client: Any | None,
        search_tool: Any | None,
        docs_tool: Any | None,
        action_tools: dict[str, Any] | None,
        search_mode: str,
        default_top_k: int = 3,
        customer_id: str = "thain-demo",
        approvals_enabled: bool = False,
    ) -> None:
        triage_agent = select_triage_agent(config.triage_mode, chat_client)
        recall_agent = None
        if config.recall_enabled and search_tool and search_mode != "off":
            recall_agent = RecallAgent(search_tool, search_mode, default_top_k)
        knowledge_agent = None
        if config.knowledge_enabled and docs_tool:
            knowledge_agent = KnowledgeAgent(docs_tool)
        action_agent = None
        if action_tools:
            action_agent = ActionAgent(
                action_tools,
                customer_id=customer_id,
                approvals_enabled=approvals_enabled,
            )

        self._orchestrator = Orchestrator(
            SafetyGateAgent(),
            triage_agent,
            recall_agent,
            knowledge_agent,
            action_agent,
        )

    async def run(self, message: str, turn_id: str) -> Blackboard:
        metadata = build_message_metadata(message)
        return await self._orchestrator.run_turn(message, turn_id, metadata)

    def context_block(self, board: Blackboard) -> str:
        return self._orchestrator.build_context_block(board)


def safe_board_snapshot(board: Blackboard) -> Dict[str, Any]:
    return blackboard_to_dict(board)

import unittest

from agents.action_agent import ActionAgent
from orchestration.contracts import Blackboard, SafetyResult, TriageResult


class ActionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_denied_by_safety(self) -> None:
        calls = {"ticket": 0}

        async def create_ticket(**kwargs):
            calls["ticket"] += 1
            return {"status": "created", "approved": True}

        tools = {"create_ticket": create_ticket}
        agent = ActionAgent(tools, customer_id="cust", approvals_enabled=True)
        board = Blackboard(
            turn_id="1",
            message={"text": "Create a ticket", "metadata": {}},
            safety=SafetyResult(
                risk_level="low",
                flags=[],
                response_mode="normal",
                tool_permissions={"create_ticket": "deny", "notify_team": "allow", "retrieve_docs": "allow", "search_similar_complaints": "allow"},
                redactions_required=[],
            ),
            triage=TriageResult(
                category="Hardware",
                urgency="high",
                needs_retrieval=False,
                needs_docs=False,
                action_candidate="ticket",
                missing_info=[],
            ),
        )
        result = await agent.run(board)
        self.assertEqual(calls["ticket"], 0)
        self.assertEqual(result.actions[0]["status"], "denied")
        self.assertEqual(result.actions[0]["reason"], "safety")

    async def test_action_executes_and_notifies(self) -> None:
        async def create_ticket(**kwargs):
            return {"status": "created", "approved": True, "ticket_id": "TCK-123"}

        notify_calls = {"related": None}

        async def notify_team(**kwargs):
            notify_calls["related"] = kwargs.get("related_ticket_id")
            return {"status": "sent", "approved": True}

        tools = {"create_ticket": create_ticket, "notify_team": notify_team}
        agent = ActionAgent(tools, customer_id="cust")
        board = Blackboard(
            turn_id="2",
            message={"text": "Create a ticket and notify the team", "metadata": {}},
            safety=SafetyResult(
                risk_level="low",
                flags=[],
                response_mode="normal",
                tool_permissions={"create_ticket": "allow", "notify_team": "allow", "retrieve_docs": "allow", "search_similar_complaints": "allow"},
                redactions_required=[],
            ),
            triage=TriageResult(
                category="Hardware",
                urgency="high",
                needs_retrieval=False,
                needs_docs=False,
                action_candidate="both",
                missing_info=[],
            ),
        )
        result = await agent.run(board)
        statuses = {action["action_type"]: action["status"] for action in result.actions}
        self.assertEqual(statuses.get("ticket"), "executed")
        self.assertEqual(statuses.get("notify"), "executed")
        self.assertEqual(notify_calls["related"], "TCK-123")

    async def test_action_denied_by_approval(self) -> None:
        async def create_ticket(**kwargs):
            return {"status": "denied", "approved": False, "reason": "approval_not_provided"}

        tools = {"create_ticket": create_ticket}
        agent = ActionAgent(tools, customer_id="cust", approvals_enabled=True)
        board = Blackboard(
            turn_id="3",
            message={"text": "Create a ticket", "metadata": {}},
            safety=SafetyResult(
                risk_level="low",
                flags=[],
                response_mode="normal",
                tool_permissions={"create_ticket": "allow", "notify_team": "allow", "retrieve_docs": "allow", "search_similar_complaints": "allow"},
                redactions_required=[],
            ),
            triage=TriageResult(
                category="Hardware",
                urgency="medium",
                needs_retrieval=False,
                needs_docs=False,
                action_candidate="ticket",
                missing_info=[],
            ),
        )
        result = await agent.run(board)
        self.assertEqual(result.actions[0]["status"], "denied")
        self.assertEqual(result.actions[0]["reason"], "approval")


if __name__ == "__main__":
    unittest.main()

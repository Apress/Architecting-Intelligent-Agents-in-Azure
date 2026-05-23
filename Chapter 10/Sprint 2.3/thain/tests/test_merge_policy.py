import unittest

from agents.orchestrator import Orchestrator
from orchestration.contracts import ActionResult, Blackboard, SafetyResult


class MergePolicyTests(unittest.TestCase):
    def test_policy_denied_action(self) -> None:
        board = Blackboard(
            turn_id="1",
            message={"text": "msg", "metadata": {}},
            safety=SafetyResult(
                risk_level="low",
                flags=[],
                response_mode="normal",
                tool_permissions={"create_ticket": "allow", "notify_team": "allow", "retrieve_docs": "allow", "search_similar_complaints": "allow"},
                redactions_required=[],
            ),
            action=ActionResult(actions=[{"action_type": "ticket", "status": "denied"}]),
        )
        policy = Orchestrator.build_response_policy(board)
        self.assertEqual(policy.action_status, "denied")
        self.assertTrue(any("not performed" in note for note in policy.enforcement_notes))

    def test_policy_safety_override(self) -> None:
        board = Blackboard(
            turn_id="2",
            message={"text": "msg", "metadata": {}},
            safety=SafetyResult(
                risk_level="high",
                flags=["self_harm"],
                response_mode="human_escalate",
                tool_permissions={"create_ticket": "deny", "notify_team": "deny", "retrieve_docs": "deny", "search_similar_complaints": "deny"},
                redactions_required=[],
            ),
        )
        policy = Orchestrator.build_response_policy(board)
        self.assertEqual(policy.response_mode, "human_escalate")
        self.assertEqual(policy.action_status, "suppressed")


if __name__ == "__main__":
    unittest.main()

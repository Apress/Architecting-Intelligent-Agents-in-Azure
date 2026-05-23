import unittest

from orchestration.contracts import SafetyResult, TriageResult
from orchestration.routing import should_run_docs, should_run_recall


class RoutingTests(unittest.TestCase):
    def test_routing_respects_permissions(self) -> None:
        triage = TriageResult(
            category="Hardware",
            urgency="high",
            needs_retrieval=True,
            needs_docs=True,
            action_candidate="ticket",
            missing_info=[],
        )
        safety = SafetyResult(
            response_mode="normal",
            tool_permissions={"search_similar_complaints": "deny", "retrieve_docs": "allow"},
            risk_level="low",
            flags=[],
            redactions_required=[],
        )
        self.assertFalse(should_run_recall(triage, safety))
        self.assertTrue(should_run_docs(triage, safety))


if __name__ == "__main__":
    unittest.main()

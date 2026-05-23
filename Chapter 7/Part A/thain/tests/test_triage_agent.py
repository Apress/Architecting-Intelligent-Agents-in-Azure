import unittest

from agents.triage_agent import TriageAgent


class TriageAgentTests(unittest.TestCase):
    def test_triage_flags_retrieval_and_ticket(self) -> None:
        agent = TriageAgent()
        message = (
            "Equipment shut down twice and caused an evacuation. "
            "Please create a ticket and tell me if there were similar incidents."
        )
        result = agent.run(message)
        self.assertEqual(result.action_candidate, "ticket")
        self.assertIn(result.urgency, {"low", "medium", "high"})
        self.assertTrue(result.needs_retrieval)
        self.assertIn(result.action_candidate, {"none", "ticket", "notify", "both"})


if __name__ == "__main__":
    unittest.main()

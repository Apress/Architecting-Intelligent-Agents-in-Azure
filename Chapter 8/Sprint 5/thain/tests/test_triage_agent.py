import unittest

from agents.triage_agent import DeterministicTriageAgent


class TriageAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_triage_flags_retrieval_and_ticket(self) -> None:
        agent = DeterministicTriageAgent()
        message = (
            "Equipment shut down twice and caused an evacuation. "
            "Please create a ticket and tell me if there were similar incidents."
        )
        result = await agent.run(message, {})
        self.assertIn(result.urgency, {"low", "medium", "high"})
        self.assertTrue(result.needs_retrieval)
        self.assertIn(result.action_candidate, {"none", "ticket", "notify", "both"})
        self.assertEqual(result.action_candidate, "ticket")

    async def test_triage_missing_info(self) -> None:
        agent = DeterministicTriageAgent()
        result = await agent.run("Create a ticket.", {})
        self.assertTrue(result.missing_info)


if __name__ == "__main__":
    unittest.main()

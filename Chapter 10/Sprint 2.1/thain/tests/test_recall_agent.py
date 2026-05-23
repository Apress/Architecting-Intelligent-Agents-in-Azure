import unittest
from datetime import datetime, timedelta, timezone

from agents.recall_agent import RecallAgent


class RecallAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_recall_recent(self) -> None:
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        async def search_tool(**kwargs):
            return [
                {
                    "id": "1",
                    "summary": "Recent incident",
                    "createdAt": recent_date,
                }
            ]

        agent = RecallAgent(search_tool, "semantic", default_top_k=2)
        result = await agent.run("shutdowns", category="Hardware")
        self.assertEqual(result.retrieval_mode, "semantic")
        self.assertEqual(result.recency, "recent")
        self.assertEqual(len(result.matches), 1)

    async def test_recall_off(self) -> None:
        agent = RecallAgent(None, "off")
        result = await agent.run("shutdowns")
        self.assertEqual(result.recency, "none")
        self.assertEqual(result.matches, [])


if __name__ == "__main__":
    unittest.main()

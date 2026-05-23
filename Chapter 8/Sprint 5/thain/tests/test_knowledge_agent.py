import unittest

from agents.knowledge_agent import KnowledgeAgent


class KnowledgeAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_docs(self) -> None:
        async def retrieve_tool(**kwargs):
            return [{"title": "Procedure", "snippet": "Steps"}]

        agent = KnowledgeAgent(retrieve_tool)
        result = await agent.run("procedure")
        self.assertEqual(len(result.docs), 1)
        self.assertEqual(result.docs[0]["title"], "Procedure")


if __name__ == "__main__":
    unittest.main()

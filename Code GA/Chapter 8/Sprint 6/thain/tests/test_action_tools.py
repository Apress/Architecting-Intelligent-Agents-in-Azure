import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import unittest

from tools.action_tools import create_action_tools


class DummyActionConfig:
    def __init__(self, tickets: bool, notifications: bool, docs: bool) -> None:
        self.enable_tickets = tickets
        self.enable_notifications = notifications
        self.enable_docs = docs


class FakeDocsService:
    async def retrieve(self, *, query: str, top_k: int | None = None, tags=None):
        _ = query
        _ = tags
        corpus = [
            {"title": "Doc 1", "snippet": "A"},
            {"title": "Doc 2", "snippet": "B"},
            {"title": "Doc 3", "snippet": "C"},
        ]
        limit = top_k or 3
        return corpus[:limit]


class FailingDocsService:
    async def retrieve(self, *, query: str, top_k: int | None = None, tags=None):
        _ = query
        _ = top_k
        _ = tags
        raise RuntimeError("boom")


class ActionToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_ticket_deterministic(self) -> None:
        cfg = DummyActionConfig(tickets=True, notifications=False, docs=False)
        tools = create_action_tools(cfg)
        self.assertEqual(len(tools), 1)
        create_ticket = tools[0]
        result1 = await create_ticket(
            summary="Repeated shutdowns",
            severity="high",
            customer_id="demo",
            evidence_summary="Similar incidents logged in past week",
            evidence_items=["Shutdown on line 2", "Evacuation triggered"],
        )
        result2 = await create_ticket(
            summary="Repeated shutdowns",
            severity="high",
            customer_id="demo",
            evidence_summary="Similar incidents logged in past week",
            evidence_items=["Shutdown on line 2", "Evacuation triggered"],
        )
        self.assertEqual(result1["ticket_id"], result2["ticket_id"])
        self.assertEqual(result1["status"], "created")

    async def test_retrieve_docs_returns_top_k(self) -> None:
        cfg = DummyActionConfig(tickets=False, notifications=False, docs=True)
        tools = create_action_tools(cfg, docs_service=FakeDocsService())
        self.assertEqual(len(tools), 1)
        retrieve_docs = tools[0]
        results = await retrieve_docs(query="shutdown", top_k=2)
        self.assertEqual(len(results), 2)
        self.assertIn("title", results[0])

    async def test_retrieve_docs_returns_trace_error_on_failure(self) -> None:
        cfg = DummyActionConfig(tickets=False, notifications=False, docs=True)
        tools = create_action_tools(cfg, docs_service=FailingDocsService())
        retrieve_docs = tools[0]
        results = await retrieve_docs(query="shutdown", top_k=2)
        self.assertEqual(len(results), 1)
        self.assertIn("_trace_error", results[0])


if __name__ == "__main__":
    unittest.main()

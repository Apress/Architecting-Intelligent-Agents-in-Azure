import unittest
from typing import Any

from services.approvals import ApprovalOutcome, requires_approval
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


class FakeApprovalService:
    def __init__(self, approved: bool) -> None:
        self._approved = approved

    @property
    def enabled(self) -> bool:
        return True

    async def request_approval(self, tool_name: str, payload: dict[str, Any]) -> ApprovalOutcome:
        _ = tool_name
        _ = payload
        status = "approved" if self._approved else "denied"
        return ApprovalOutcome(
            approval_id="APR-TEST",
            tool_name=tool_name,
            approved=self._approved,
            status=status,
            reason="approved" if self._approved else "approval_denied",
        )

    async def try_mark_executed(self, approval_id: str) -> bool:
        _ = approval_id
        return self._approved


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_tool_denied_when_not_approved(self) -> None:
        cfg = DummyActionConfig(tickets=True, notifications=False, docs=False)
        approvals = FakeApprovalService(approved=False)
        tools = create_action_tools(cfg, approvals)
        self.assertEqual(len(tools), 1)
        create_ticket = tools[0]
        result = await create_ticket(
            summary="Repeated shutdowns",
            severity="high",
            customer_id="demo",
            evidence_summary="Similar incidents logged in past week",
            evidence_items=["Shutdown on line 2"],
        )
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["approved"], False)
        self.assertEqual(result["reason"], "approval_denied")

    async def test_read_tool_bypasses_approval(self) -> None:
        cfg = DummyActionConfig(tickets=False, notifications=False, docs=True)
        approvals = FakeApprovalService(approved=False)
        tools = create_action_tools(cfg, approvals, docs_service=FakeDocsService())
        self.assertEqual(len(tools), 1)
        retrieve_docs = tools[0]
        results = await retrieve_docs(query="shutdown", top_k=2)
        self.assertEqual(len(results), 2)

    def test_requires_approval_by_type(self) -> None:
        self.assertTrue(requires_approval("write", True))
        self.assertFalse(requires_approval("read", True))
        self.assertFalse(requires_approval("write", False))


if __name__ == "__main__":
    unittest.main()

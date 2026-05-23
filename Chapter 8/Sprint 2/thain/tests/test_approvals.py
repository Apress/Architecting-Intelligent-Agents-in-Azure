import unittest

from services.approvals import ApprovalService, requires_approval
from tools.action_tools import create_action_tools


class DummyActionConfig:
    def __init__(self, tickets: bool, notifications: bool, docs: bool) -> None:
        self.enable_tickets = tickets
        self.enable_notifications = notifications
        self.enable_docs = docs


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_tool_denied_when_not_approved(self) -> None:
        cfg = DummyActionConfig(tickets=True, notifications=False, docs=False)
        approvals = ApprovalService(enabled=True, prompt=lambda _: "n")
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
        self.assertEqual(result["reason"], "approval_not_provided")

    async def test_read_tool_bypasses_approval(self) -> None:
        cfg = DummyActionConfig(tickets=False, notifications=False, docs=True)
        approvals = ApprovalService(enabled=True, prompt=lambda _: "n")
        tools = create_action_tools(cfg, approvals)
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

import unittest

from main import _wrap_tool
from agent_framework import tool
from observability.tracing import TraceRecorder


class PolicyTracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_denied_logs_blocked(self) -> None:
        recorder = TraceRecorder(run_id="run1", trace_id="trace1", turn_id=1)

        @tool(name="create_ticket")
        async def create_ticket(summary: str) -> dict[str, str]:
            return {"status": "created"}

        policy_state = {"approvals_enabled": False, "policy_requires_approval": True}
        wrapped = _wrap_tool(create_ticket, recorder, policy_state)
        result = await wrapped(summary="test")
        self.assertEqual(result, [])
        events = recorder.to_dict()["events"]
        event_types = [event["type"] for event in events]
        self.assertIn("policy.check", event_types)
        tool_results = [event for event in events if event["type"] == "tool.result"]
        self.assertEqual(tool_results[-1]["data"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

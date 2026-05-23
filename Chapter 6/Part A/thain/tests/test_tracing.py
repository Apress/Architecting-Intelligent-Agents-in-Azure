import unittest

from main import _wrap_tool
from agent_framework import ai_function
from observability.tracing import TraceRecorder


class TracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_seq_increases(self) -> None:
        recorder = TraceRecorder(run_id="run1", trace_id="trace1", turn_id=1)
        recorder.record("request.received", {"message_len": 4})
        recorder.record("response.ready", {"category": "General", "summary": "ok"})
        events = recorder.to_dict()["events"]
        self.assertEqual([1, 2], [event["seq"] for event in events])

    async def test_tool_wrapper_records_events(self) -> None:
        recorder = TraceRecorder(run_id="run1", trace_id="trace1", turn_id=1)

        @ai_function
        async def sample_tool(query: str) -> dict[str, str]:
            return {"result": f"echo {query}"}

        wrapped = _wrap_tool(sample_tool, recorder)
        await wrapped(query="ping")
        events = recorder.to_dict()["events"]
        event_types = [event["type"] for event in events]
        self.assertIn("tool.call", event_types)
        self.assertIn("tool.result", event_types)

    async def test_tool_error_records_result(self) -> None:
        recorder = TraceRecorder(run_id="run1", trace_id="trace1", turn_id=1)

        @ai_function
        async def bad_tool() -> None:
            raise ValueError("boom")

        wrapped = _wrap_tool(bad_tool, recorder)
        with self.assertRaises(ValueError):
            await wrapped()
        events = recorder.to_dict()["events"]
        last = events[-1]
        self.assertEqual(last["type"], "tool.result")
        self.assertEqual(last["data"]["status"], "error")


if __name__ == "__main__":
    unittest.main()

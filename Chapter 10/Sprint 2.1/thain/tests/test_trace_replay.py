import json
import tempfile
import unittest
from pathlib import Path

from audit.trace_replay import render_trace_summary


class TraceReplayTests(unittest.TestCase):
    def test_render_trace_summary(self) -> None:
        trace = {
            "schema_version": "0.1",
            "context": {"run_id": "run1", "trace_id": "trace1", "turn_id": 1, "elapsed_ms": 12},
            "events": [
                {"type": "policy.check", "data": {"tool_name": "create_ticket", "decision": "deny", "matched_rule_ids": ["POL-DENY-001"]}},
                {"type": "tool.result", "data": {"tool_name": "create_ticket", "status": "blocked", "error_type": "PolicyDenied"}},
                {"type": "response.ready", "data": {"category": "General Inquiry", "summary_len": 12, "elapsed_ms": 12}},
            ],
        }
        summary = render_trace_summary(trace)
        self.assertIn("trace1", summary)
        self.assertIn("POL-DENY-001", summary)
        self.assertIn("create_ticket", summary)


if __name__ == "__main__":
    unittest.main()

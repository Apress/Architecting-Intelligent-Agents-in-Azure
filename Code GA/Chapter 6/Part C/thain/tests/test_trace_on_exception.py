import os
import tempfile
import unittest
from pathlib import Path

from observability.tracing import TraceRecorder
from main import _emit_trace


class TraceOnExceptionTests(unittest.TestCase):
    def test_trace_emitted_on_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["TRACE_OUTPUT_DIR"] = tmpdir
            recorder = TraceRecorder(run_id="runx", trace_id="tracex", turn_id=1)
            recorder.record("request.received", {"message_len": 5, "has_urls": False, "safety_flags": []})
            # simulate exception flow
            recorder.record("error.occurred", {"error_type": "ToolExecutionError", "message": "boom", "stage": "run", "tool_name": None})
            path = _emit_trace(recorder)
            trace = Path(path).read_text(encoding="utf-8")
            self.assertIn("trace.emitted", trace)
            self.assertIn("error.occurred", trace)


if __name__ == "__main__":
    unittest.main()

import unittest

from governance.logging_policy import apply_log_policy


class LoggingPolicyTests(unittest.TestCase):
    def test_filters_allowed_fields(self) -> None:
        payload = {
            "tool_name": "create_ticket",
            "args": {"summary": "secret"},
            "extra": "drop",
        }
        filtered = apply_log_policy("tool.call", payload)
        self.assertIn("tool_name", filtered)
        self.assertIn("args", filtered)
        self.assertNotIn("extra", filtered)

    def test_unknown_event_returns_empty(self) -> None:
        filtered = apply_log_policy("unknown", {"foo": "bar"})
        self.assertEqual(filtered, {})


if __name__ == "__main__":
    unittest.main()

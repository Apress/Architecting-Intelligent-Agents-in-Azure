import unittest

from agents.safety_gate import SafetyGateAgent


class SafetyGateTests(unittest.TestCase):
    def test_self_harm_escalates(self) -> None:
        gate = SafetyGateAgent()
        result = gate.run("I want to kill myself.", {})
        self.assertEqual(result.response_mode, "human_escalate")
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.tool_permissions.get("create_ticket"), "deny")

    def test_hate_refuses(self) -> None:
        gate = SafetyGateAgent()
        result = gate.run("That is a Nazi policy.", {})
        self.assertEqual(result.response_mode, "refuse")
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.tool_permissions.get("notify_team"), "deny")

    def test_pii_redaction_flag(self) -> None:
        gate = SafetyGateAgent()
        result = gate.run("Email me at user@example.com.", {})
        self.assertIn("pii", result.redactions_required)


if __name__ == "__main__":
    unittest.main()

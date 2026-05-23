import unittest

from governance.policy import PolicyDecision, PolicyEngine, PolicyRule


class PolicyTests(unittest.TestCase):
    def test_allow_when_no_rules(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate("read", {"approvals_enabled": True})
        self.assertEqual(decision.decision, "allow")
        self.assertEqual(decision.matched_rule_ids, [])

    def test_deny_takes_precedence(self) -> None:
        rules = [
            PolicyRule("WARN_READ", "warn reads", "warn", {"read"}),
            PolicyRule("DENY_READ", "deny reads", "deny", {"read"}),
        ]
        engine = PolicyEngine(rules)
        decision = engine.evaluate("read", {"approvals_enabled": True})
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(decision.enforced_rule_id, "DENY_READ")

    def test_warn_when_only_warn(self) -> None:
        rules = [PolicyRule("WARN_WRITE", "warn writes", "warn", {"write"})]
        engine = PolicyEngine(rules)
        decision = engine.evaluate("write", {"approvals_enabled": True})
        self.assertEqual(decision.decision, "warn")


    def test_deny_when_approvals_disabled(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate(
            "write",
            {"approvals_enabled": False, "policy_requires_approval": True},
        )
        self.assertEqual(decision.decision, "deny")
        self.assertIn("POL-DENY-001", decision.matched_rule_ids)

    def test_warn_when_write_calls_exceed_threshold(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate(
            "write",
            {"approvals_enabled": True, "write_calls_in_turn": 2, "warn_write_threshold": 2},
        )
        self.assertEqual(decision.decision, "warn")
        self.assertIn("POL-WARN-001", decision.matched_rule_ids)


    def test_deny_retrieval_when_not_agentic(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate(
            "retrieve",
            {"approvals_enabled": True, "search_mode": "semantic"},
        )
        self.assertEqual(decision.decision, "deny")
        self.assertIn("POL-DENY-002", decision.matched_rule_ids)

    def test_deny_write_with_pii_flags(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate(
            "ticket",
            {
                "approvals_enabled": True,
                "pii_write_block": True,
                "safety_flags": ["contains_email"],
            },
        )
        self.assertEqual(decision.decision, "deny")
        self.assertIn("POL-DENY-004", decision.matched_rule_ids)

    def test_warn_when_action_without_retrieval(self) -> None:
        engine = PolicyEngine([])
        decision = engine.evaluate(
            "ticket",
            {
                "approvals_enabled": True,
                "retrieval_attempted": True,
                "retrieval_results_count": 0,
            },
        )
        self.assertEqual(decision.decision, "warn")
        self.assertIn("POL-WARN-002", decision.matched_rule_ids)


if __name__ == "__main__":
    unittest.main()

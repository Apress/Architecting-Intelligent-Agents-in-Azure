import unittest

from governance.safety import detect_safety_flags, unique_flags


class SafetyFlagTests(unittest.TestCase):
    def test_detects_basic_flags(self) -> None:
        text = "Email me at test@example.com or call +1 555 123 4567."
        flags = detect_safety_flags(text)
        self.assertIn("contains_email", flags)
        self.assertIn("contains_phone", flags)

    def test_unique_flags_sorted(self) -> None:
        flags = unique_flags(["contains_email", "contains_email", "contains_phone"])
        self.assertEqual(flags, ["contains_email", "contains_phone"])


if __name__ == "__main__":
    unittest.main()

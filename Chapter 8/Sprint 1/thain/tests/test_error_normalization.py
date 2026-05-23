import asyncio
import unittest
from pathlib import Path

from governance.errors import normalize_error
from memory.semantic_service import SemanticSearchError


class ErrorNormalizationTests(unittest.TestCase):
    def test_normalize_external_service(self) -> None:
        error = normalize_error(SemanticSearchError("boom"), stage="tool")
        self.assertEqual(error.error_type, "SemanticSearchError")

    def test_normalize_timeout(self) -> None:
        error = normalize_error(asyncio.TimeoutError(), stage="run")
        self.assertIn("Timeout", error.error_type)


if __name__ == "__main__":
    unittest.main()

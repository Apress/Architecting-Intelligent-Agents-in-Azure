import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import unittest
from unittest.mock import AsyncMock, MagicMock

from tools.search import create_search_tool


class DummyConfig:
    def __init__(self, mode: str = "agentic") -> None:
        self.customer_id = "demo"
        self.default_top_k = 3
        self.mode = mode


class AgenticSearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_agentic_tool_calls_service_with_params(self) -> None:
        cfg = DummyConfig(mode="agentic")
        service = MagicMock()
        expected = [{"id": "1", "summary": "match"}]
        service.find_similar = AsyncMock(return_value=expected)

        tool = create_search_tool(service, cfg)
        result = await tool(
            customer_message="serious issue",
            top_k=2,
            category="safety",
            time_window_days=45,
            include_outcomes=True,
        )

        self.assertEqual(result, expected)
        service.find_similar.assert_awaited_once_with(
            customer_id="demo",
            text="serious issue",
            category="safety",
            top_k=2,
            time_window_days=45,
            include_outcomes=True,
        )

    async def test_tool_returns_empty_when_mode_off(self) -> None:
        cfg = DummyConfig(mode="off")
        service = MagicMock()
        service.find_similar = AsyncMock()

        tool = create_search_tool(service, cfg)
        result = await tool(customer_message="irrelevant")

        self.assertEqual(result, [])
        service.find_similar.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
# touch

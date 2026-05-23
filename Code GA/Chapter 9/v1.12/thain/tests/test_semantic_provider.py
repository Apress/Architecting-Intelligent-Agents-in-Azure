import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from memory.semantic_provider import SemanticContextProvider
from memory.semantic_service import SemanticSearchError


def _make_mock_context(user_message: str = "New Wi-Fi issue") -> MagicMock:
    msg = MagicMock()
    msg.role = "user"
    msg.text = user_message

    ctx = MagicMock()
    ctx.input_messages = [msg]
    ctx.instructions = []
    return ctx


class SemanticContextProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_source_id(self) -> None:
        service = MagicMock()
        provider = SemanticContextProvider(service=service, customer_id="demo")
        self.assertEqual(provider.source_id, "semantic-recall")

    async def test_instructions_emitted_when_results_available(self) -> None:
        service = MagicMock()
        service.find_similar = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "issueCategory": "Connectivity",
                    "summary": "Wi-Fi dropped repeatedly yesterday.",
                    "rawMessage": "Wi-Fi dropped repeatedly yesterday.",
                    "createdAt": datetime.now(timezone.utc),
                }
            ]
        )

        provider = SemanticContextProvider(service=service, customer_id="demo", lookup_limit=2)
        ctx = _make_mock_context("New Wi-Fi issue")
        await provider.before_run(agent=None, session=None, context=ctx, state={})

        self.assertEqual(len(ctx.instructions), 1)
        self.assertIn("Connectivity", ctx.instructions[0])
        service.find_similar.assert_awaited()

    async def test_graceful_fallback_on_error(self) -> None:
        service = MagicMock()
        service.find_similar = AsyncMock(side_effect=SemanticSearchError("offline"))

        provider = SemanticContextProvider(service=service, customer_id="demo", lookup_limit=2)
        ctx = _make_mock_context("Another issue")
        await provider.before_run(agent=None, session=None, context=ctx, state={})

        self.assertEqual(ctx.instructions, [])

    async def test_no_instructions_when_mode_disabled(self) -> None:
        service = MagicMock()
        service.find_similar = AsyncMock(return_value=[])

        provider = SemanticContextProvider(service=service, customer_id="demo", mode="off")
        ctx = _make_mock_context("Some message")
        await provider.before_run(agent=None, session=None, context=ctx, state={})

        self.assertEqual(ctx.instructions, [])
        service.find_similar.assert_not_awaited()

    async def test_no_instructions_when_no_results(self) -> None:
        service = MagicMock()
        service.find_similar = AsyncMock(return_value=[])

        provider = SemanticContextProvider(service=service, customer_id="demo", lookup_limit=3)
        ctx = _make_mock_context("Battery draining fast")
        await provider.before_run(agent=None, session=None, context=ctx, state={})

        self.assertEqual(ctx.instructions, [])

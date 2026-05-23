import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from agent_framework import Context

from memory.semantic_provider import SemanticContextProvider
from memory.semantic_service import SemanticSearchError


class SemanticContextProviderTests(unittest.IsolatedAsyncioTestCase):
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
        context = await provider.invoking("New Wi-Fi issue")
        self.assertIsInstance(context, Context)
        self.assertIn("Connectivity", context.instructions or "")
        service.find_similar.assert_awaited()

    async def test_graceful_fallback_on_error(self) -> None:
        service = MagicMock()
        service.find_similar = AsyncMock(side_effect=SemanticSearchError("offline"))

        provider = SemanticContextProvider(service=service, customer_id="demo", lookup_limit=2)
        context = await provider.invoking("Another issue")
        self.assertFalse(context.instructions)

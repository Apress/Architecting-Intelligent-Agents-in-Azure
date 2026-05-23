import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from config.settings import PersistentMemoryConfig
from memory.persistence import PersistentMemoryService, PersistentStoreError
from memory.persistent_provider import PersistentContextProvider
from models.complaint import ComplaintRecordModel


def _sample_record(summary: str = "Wi-Fi issues") -> ComplaintRecordModel:
    return ComplaintRecordModel(
        customerId="thain-demo",
        issueCategory="Connectivity",
        summary=summary,
        rawMessage="Wi-Fi keeps dropping",
        confidence=0.8,
        createdAt=datetime.now(timezone.utc),
    )


def _make_mock_context(customer_id=None):
    ctx = MagicMock()
    ctx.metadata = {"customer_id": customer_id} if customer_id else {}
    ctx.input_messages = []
    ctx.instructions = []
    return ctx


class PersistentMemoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = PersistentMemoryConfig(
            endpoint="https://example.documents.azure.com:443/",
            key="fake-key",
            database="db",
            container="container",
            ttl_days=30,
            customer_id="thain-demo",
        )

    async def test_persist_calls_repository_and_clears_cache(self) -> None:
        repo = MagicMock()
        repo.upsert_complaint = AsyncMock()
        repo.fetch_recent = AsyncMock(return_value=[_sample_record()])

        service = PersistentMemoryService(self.config, repository=repo)

        # Warm the cache
        await service.fetch_recent(customer_id="thain-demo")
        repo.fetch_recent.assert_awaited()
        repo.fetch_recent.reset_mock()

        await service.persist(
            customer_id="thain-demo",
            category="Connectivity",
            summary="Wi-Fi keeps dropping",
            message="Wi-Fi keeps dropping",
            confidence=0.9,
        )
        repo.upsert_complaint.assert_awaited()

        # Cache should be cleared so repository is invoked again
        await service.fetch_recent(customer_id="thain-demo")
        repo.fetch_recent.assert_awaited()

    async def test_fetch_recent_propagates_store_errors(self) -> None:
        repo = MagicMock()
        repo.fetch_recent = AsyncMock(side_effect=PersistentStoreError("offline"))

        service = PersistentMemoryService(self.config, repository=repo)

        with self.assertRaises(PersistentStoreError):
            await service.fetch_recent(customer_id="thain-demo")


class PersistentContextProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = PersistentMemoryConfig(
            endpoint="https://example.documents.azure.com:443/",
            key="fake-key",
            database="db",
            container="container",
            ttl_days=30,
            customer_id="thain-demo",
        )

    async def test_provider_source_id(self) -> None:
        service = MagicMock(spec=PersistentMemoryService)
        service.fetch_recent = AsyncMock(return_value=[])
        provider = PersistentContextProvider(
            memory_service=service,
            default_customer_id="thain-demo",
        )
        self.assertEqual(provider.source_id, "persistent-memory")

    async def test_provider_handles_store_error(self) -> None:
        service = MagicMock(spec=PersistentMemoryService)
        service.fetch_recent = AsyncMock(side_effect=PersistentStoreError("offline"))

        provider = PersistentContextProvider(
            memory_service=service,
            default_customer_id="thain-demo",
            lookup_limit=5,
        )

        ctx = _make_mock_context(customer_id="thain-demo")
        await provider.before_run(agent=None, session=None, context=ctx, state={})
        self.assertEqual(ctx.instructions, [])

    async def test_provider_injects_instructions_when_records_present(self) -> None:
        service = MagicMock(spec=PersistentMemoryService)
        service.fetch_recent = AsyncMock(return_value=[_sample_record("Wi-Fi issues")])

        provider = PersistentContextProvider(
            memory_service=service,
            default_customer_id="thain-demo",
            lookup_limit=5,
        )

        ctx = _make_mock_context(customer_id="thain-demo")
        await provider.before_run(agent=None, session=None, context=ctx, state={})
        self.assertTrue(len(ctx.instructions) > 0)
        self.assertIn("Wi-Fi issues", ctx.instructions[0])

    async def test_provider_uses_metadata_customer_id(self) -> None:
        service = MagicMock(spec=PersistentMemoryService)
        service.fetch_recent = AsyncMock(return_value=[])

        provider = PersistentContextProvider(
            memory_service=service,
            default_customer_id="default-customer",
            lookup_limit=5,
        )

        ctx = _make_mock_context(customer_id="override-customer")
        await provider.before_run(agent=None, session=None, context=ctx, state={})
        service.fetch_recent.assert_awaited_with(customer_id="override-customer", limit=5)

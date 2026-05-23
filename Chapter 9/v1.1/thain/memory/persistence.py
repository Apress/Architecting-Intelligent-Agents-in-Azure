from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from config.settings import PersistentMemoryConfig
from azure.core.credentials import TokenCredential

from memory.repositories import CosmosRepository, PersistentStoreError
from models.complaint import ComplaintQuery, ComplaintRecordModel

logger = logging.getLogger(__name__)


class _LRUCache:
    """Simple TTL-aware LRU cache for query results."""

    def __init__(self, capacity: int = 32, ttl_seconds: int = 30) -> None:
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[datetime, list[ComplaintRecordModel]]] = OrderedDict()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get(self, key: str) -> Optional[list[ComplaintRecordModel]]:
        entry = self._store.get(key)
        if not entry:
            return None
        timestamp, value = entry
        if (self._now() - timestamp).total_seconds() > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: list[ComplaintRecordModel]) -> None:
        self._store[key] = (self._now(), value)
        self._store.move_to_end(key)
        if len(self._store) > self.capacity:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


class PersistentMemoryService:
    """Coordinates storing and retrieving complaints from Cosmos DB."""

    def __init__(
        self,
        config: PersistentMemoryConfig,
        repository: CosmosRepository | None = None,
        credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        self._repository = repository or CosmosRepository(config, credential=credential)
        self._cache = _LRUCache()

    async def persist(
        self,
        *,
        customer_id: str,
        category: str,
        summary: str,
        message: str,
        confidence: float = 1.0,
        embedding_id: str | None = None,
    ) -> None:
        record = ComplaintRecordModel.from_agent_payload(
            customer_id=customer_id,
            category=category,
            summary=summary,
            message=message,
            confidence=confidence,
            ttl_seconds=self._config.ttl_seconds or None,
        )
        if embedding_id:
            record.embedding_id = embedding_id

        try:
            await self._repository.upsert_complaint(record)
        except PersistentStoreError:
            raise
        except Exception as exc:
            logger.warning("Unexpected failure while persisting complaint: %s", exc, exc_info=True)
            raise PersistentStoreError("Persistent memory write failed.") from exc
        finally:
            self._cache.clear()

    async def fetch_recent(
        self,
        *,
        customer_id: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[ComplaintRecordModel]:
        cache_key = f"{customer_id}:{category}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        query = ComplaintQuery(customerId=customer_id, category=category, limit=limit)
        try:
            results = await self._repository.fetch_recent(query)
            self._cache.set(cache_key, results)
            return results
        except PersistentStoreError:
            raise
        except Exception as exc:
            logger.warning("Unexpected error fetching persistent context: %s", exc, exc_info=True)
            raise PersistentStoreError("Persistent memory read failed.") from exc

    async def close(self) -> None:
        await self._repository.close()
        self._cache.clear()

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from azure.core.credentials import TokenCredential
from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError

from config.settings import FeedbackConfig

logger = logging.getLogger(__name__)


class FeedbackStoreError(RuntimeError):
    """Raised when the feedback store cannot be accessed."""


class FeedbackStore:
    """Async Cosmos DB store for feedback records."""

    def __init__(
        self,
        config: FeedbackConfig,
        credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        if not self._config.key and not credential:
            raise FeedbackStoreError("Cosmos credential is required when COSMOS_KEY is not provided.")
        self._client = CosmosClient(self._config.endpoint, credential=self._config.key or credential)
        self._database = None
        self._container = None

    async def _ensure_container(self) -> Any:
        if self._container:
            return self._container

        try:
            self._database = await self._client.create_database_if_not_exists(id=self._config.database)
        except Exception as exc:
            logger.error("Failed to access Cosmos DB database '%s': %s", self._config.database, exc, exc_info=True)
            raise FeedbackStoreError("Unable to access Cosmos DB database.") from exc

        try:
            kwargs: dict[str, Any] = {}
            if self._config.ttl_seconds:
                kwargs["default_ttl"] = self._config.ttl_seconds
            try:
                self._container = await self._database.create_container_if_not_exists(
                    id=self._config.container,
                    partition_key=PartitionKey(path="/scenario"),
                    **kwargs,
                )
            except Exception as exc:
                if "serverless" not in str(exc).lower():
                    raise
                self._container = await self._database.create_container_if_not_exists(
                    id=self._config.container,
                    partition_key=PartitionKey(path="/scenario"),
                    **kwargs,
                )
        except CosmosResourceExistsError:
            self._container = await self._database.get_container_client(self._config.container)
        except Exception as exc:
            logger.error("Failed to access Cosmos DB container '%s': %s", self._config.container, exc, exc_info=True)
            raise FeedbackStoreError("Unable to access Cosmos DB container.") from exc

        return self._container

    async def create(self, record: dict[str, Any]) -> dict[str, Any]:
        container = await self._ensure_container()
        payload = dict(record)
        if payload.get("ttl") is None and self._config.ttl_seconds:
            payload["ttl"] = self._config.ttl_seconds
        if not payload.get("created_at_utc"):
            payload["created_at_utc"] = datetime.now(timezone.utc).isoformat()
        if not payload.get("scenario"):
            payload["scenario"] = "answer"
        try:
            await container.create_item(payload)
            return payload
        except Exception as exc:
            logger.warning("Failed to create feedback record: %s", exc, exc_info=True)
            raise FeedbackStoreError("Unable to create feedback record.") from exc

    async def get(self, record_id: str) -> dict[str, Any] | None:
        container = await self._ensure_container()
        try:
            query = "SELECT * FROM c WHERE c.id = @id"
            params = [{"name": "@id", "value": record_id}]
            items = container.query_items(query=query, parameters=params)
            async for item in items:
                return item
            return None
        except Exception as exc:
            logger.warning("Failed to read feedback record: %s", exc, exc_info=True)
            raise FeedbackStoreError("Unable to read feedback record.") from exc

    async def list_range(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        container = await self._ensure_container()
        query = (
            "SELECT * FROM c WHERE c.created_at_utc >= @start AND c.created_at_utc <= @end "
            "ORDER BY c.created_at_utc DESC"
        )
        params = [
            {"name": "@start", "value": start_iso},
            {"name": "@end", "value": end_iso},
        ]
        items = container.query_items(query=query, parameters=params)
        results: list[dict[str, Any]] = []
        async for item in items:
            results.append(item)
        return results

    async def close(self) -> None:
        await self._client.close()

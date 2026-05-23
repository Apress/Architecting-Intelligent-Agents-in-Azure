from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError

from config.settings import PersistentMemoryConfig
from models.complaint import ComplaintQuery, ComplaintRecordModel

logger = logging.getLogger(__name__)


class PersistentStoreError(RuntimeError):
    """Raised when the persistent store cannot be reached."""


class CosmosRepository:
    """Async Cosmos DB repository for complaint records."""

    def __init__(self, config: PersistentMemoryConfig) -> None:
        self._config = config
        self._client = CosmosClient(self._config.endpoint, credential=self._config.key)
        self._database = None
        self._container = None

    async def _ensure_container(self) -> Any:
        if self._container:
            return self._container

        try:
            self._database = await self._client.create_database_if_not_exists(id=self._config.database)
        except Exception as exc:
            logger.error("Failed to access Cosmos database '%s': %s", self._config.database, exc, exc_info=True)
            raise PersistentStoreError("Unable to access Cosmos DB database.") from exc

        try:
            kwargs: dict[str, Any] = {}
            if self._config.ttl_seconds:
                kwargs["default_ttl"] = self._config.ttl_seconds

            self._container = await self._database.create_container_if_not_exists(
                id=self._config.container,
                partition_key=PartitionKey(path="/customerId"),
                **kwargs,
            )
        except CosmosResourceExistsError:
            self._container = await self._database.get_container_client(self._config.container)
        except Exception as exc:
            logger.error("Failed to access Cosmos container '%s': %s", self._config.container, exc, exc_info=True)
            raise PersistentStoreError("Unable to access Cosmos DB container.") from exc

        return self._container

    async def upsert_complaint(self, record: ComplaintRecordModel) -> None:
        container = await self._ensure_container()
        try:
            payload = record.model_dump(by_alias=True)
            payload["createdAt"] = record.created_at.isoformat()
            if payload.get("ttl") is None and self._config.ttl_seconds:
                payload["ttl"] = self._config.ttl_seconds
            await container.upsert_item(payload)
        except Exception as exc:
            logger.warning("Failed to upsert complaint record to Cosmos DB: %s", exc, exc_info=True)
            raise PersistentStoreError("Unable to write to Cosmos DB.") from exc

    async def fetch_recent(self, query: ComplaintQuery) -> list[ComplaintRecordModel]:
        container = await self._ensure_container()
        parameters = [
            {"name": "@limit", "value": query.limit},
            {"name": "@partitionKey", "value": query.customer_id},
        ]
        where_clause = "c.customerId = @partitionKey"
        if query.category:
            where_clause += " AND c.issueCategory = @category"
            parameters.append({"name": "@category", "value": query.category})

        cosmos_query = (
            f"SELECT TOP @limit * FROM c "
            f"WHERE {where_clause} "
            f"ORDER BY c.createdAt DESC"
        )

        try:
            items = container.query_items(
                query=cosmos_query,
                parameters=parameters,
                partition_key=query.customer_id,
                max_item_count=query.limit,
            )
            results: list[ComplaintRecordModel] = []
            async for item in items:
                results.append(ComplaintRecordModel.model_validate(item))
            return results
        except Exception as exc:
            logger.warning("Failed to fetch complaints from Cosmos DB: %s", exc, exc_info=True)
            raise PersistentStoreError("Unable to read from Cosmos DB.") from exc

    async def close(self) -> None:
        await self._client.close()

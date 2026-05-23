from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from azure.core import MatchConditions
from azure.core.credentials import TokenCredential
from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from config.settings import ApprovalStoreConfig

logger = logging.getLogger(__name__)


class ApprovalStoreError(RuntimeError):
    """Raised when the approval store cannot be accessed."""


class CosmosApprovalStore:
    """Async Cosmos DB store for approval records."""

    def __init__(
        self,
        config: ApprovalStoreConfig,
        credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        if not self._config.key and not credential:
            raise ApprovalStoreError("Cosmos credential is required when COSMOS_KEY is not provided.")
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
            raise ApprovalStoreError("Unable to access Cosmos DB database.") from exc

        try:
            kwargs: dict[str, Any] = {}
            if self._config.ttl_seconds:
                kwargs["default_ttl"] = self._config.ttl_seconds
            self._container = await self._database.create_container_if_not_exists(
                id=self._config.container,
                partition_key=PartitionKey(path="/approval_id"),
                **kwargs,
            )
        except CosmosResourceExistsError:
            self._container = await self._database.get_container_client(self._config.container)
        except Exception as exc:
            logger.error("Failed to access Cosmos DB container '%s': %s", self._config.container, exc, exc_info=True)
            raise ApprovalStoreError("Unable to access Cosmos DB container.") from exc

        return self._container

    async def create_request(self, record: dict[str, Any]) -> dict[str, Any]:
        container = await self._ensure_container()
        payload = dict(record)
        payload.setdefault("id", payload.get("approval_id"))
        if payload.get("ttl") is None and self._config.ttl_seconds:
            payload["ttl"] = self._config.ttl_seconds
        try:
            await container.create_item(payload)
            return payload
        except Exception as exc:
            logger.warning("Failed to create approval record: %s", exc, exc_info=True)
            raise ApprovalStoreError("Unable to create approval record.") from exc

    async def get(self, approval_id: str) -> dict[str, Any] | None:
        container = await self._ensure_container()
        try:
            return await container.read_item(item=approval_id, partition_key=approval_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            logger.warning("Failed to read approval record: %s", exc, exc_info=True)
            raise ApprovalStoreError("Unable to read approval record.") from exc

    async def record_decision(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str | None,
        decision_source: str | None,
        decided_at: str | None = None,
    ) -> dict[str, Any] | None:
        container = await self._ensure_container()
        record = await self.get(approval_id)
        if record is None:
            return None

        current_status = str(record.get("status") or "pending")
        if current_status in {"approved", "denied", "expired", "executed"}:
            return record

        now = datetime.now(timezone.utc)
        expires_at_raw = record.get("expires_at")
        if expires_at_raw:
            try:
                expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        else:
            expires_at = None

        final_decision = decision.lower()
        if expires_at and now > expires_at:
            final_decision = "expired"

        updated = dict(record)
        updated["decision"] = final_decision
        updated["approved"] = final_decision == "approved"
        updated["status"] = final_decision
        updated["decided_by"] = decided_by or "unknown"
        updated["decision_source"] = decision_source or "callback"
        updated["callback_received_at"] = now.isoformat()
        updated["finalized_at"] = now.isoformat()
        updated["decided_at"] = decided_at or now.isoformat()
        if final_decision in {"denied", "expired"}:
            updated["execution_status"] = final_decision

        etag = record.get("_etag")
        try:
            return await container.replace_item(
                item=approval_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            logger.warning("Failed to record approval decision: %s", exc, exc_info=True)
            return await self.get(approval_id)

    async def mark_executed(self, approval_id: str, executor_run_id: str | None = None) -> bool:
        container = await self._ensure_container()
        record = await self.get(approval_id)
        if record is None:
            return False

        status = str(record.get("status") or "pending")
        if status not in {"approved", "executed"}:
            return False
        if record.get("execution_status") == "executed":
            return False

        updated = dict(record)
        updated["execution_status"] = "executed"
        updated["executed_at"] = datetime.now(timezone.utc).isoformat()
        if executor_run_id:
            updated["executor_run_id"] = executor_run_id
        updated["status"] = "executed"

        etag = record.get("_etag")
        try:
            await container.replace_item(
                item=approval_id,
                body=updated,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to mark approval executed: %s", exc, exc_info=True)
            return False

    async def close(self) -> None:
        await self._client.close()

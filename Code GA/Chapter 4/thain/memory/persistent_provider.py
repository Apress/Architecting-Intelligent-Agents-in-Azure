from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable, Optional

from agent_framework import ContextProvider, SessionContext

from memory.persistence import PersistentMemoryService, PersistentStoreError

logger = logging.getLogger(__name__)
AEST_TZ = timezone(timedelta(hours=10))


class PersistentContextProvider(ContextProvider):
    """Loads long-term memories from Cosmos DB and surfaces them as context instructions."""

    def __init__(
        self,
        *,
        memory_service: PersistentMemoryService,
        default_customer_id: str,
        lookup_limit: int = 5,
    ) -> None:
        super().__init__(source_id="persistent-memory")
        self._memory_service = memory_service
        self._default_customer_id = default_customer_id
        self._lookup_limit = lookup_limit

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: SessionContext,
        state: dict,
    ) -> None:
        customer_id = context.metadata.get("customer_id") or self._default_customer_id
        try:
            records = await self._memory_service.fetch_recent(customer_id=customer_id, limit=self._lookup_limit)
        except PersistentStoreError:
            logger.debug("Persistent memory unavailable; continuing without durable context.", exc_info=True)
            return

        if not records:
            logger.info("PersistentContextProvider: no records for customer '%s'.", customer_id)
            return

        logger.info("PersistentContextProvider: returning %d stored record(s) for customer '%s'.", len(records), customer_id)

        formatted = [
            f"- [{record.issue_category}] {record.summary} ({record.created_at.astimezone(AEST_TZ).strftime('%d/%m/%y %H:%M AEST')})"
            for record in records
        ]

        instructions = (
            "Consider the following recent complaints from persistent memory:\n"
            + "\n".join(formatted)
        )

        context.instructions.append(instructions)

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable, Optional

from agent_framework import ChatMessage, Context, ContextProvider

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
        self._memory_service = memory_service
        self._default_customer_id = default_customer_id
        self._lookup_limit = lookup_limit

    async def invoking(self, messages: Any, **kwargs: Any) -> Context:  # type: ignore[override]
        customer_id = kwargs.get("customer_id") or self._default_customer_id
        query_text = _extract_user_text(messages)
        try:
            records = await self._memory_service.fetch_recent(customer_id=customer_id, limit=self._lookup_limit)
        except PersistentStoreError:
            logger.debug("Persistent memory unavailable; continuing without durable context.", exc_info=True)
            return Context()

        if not records:
            logger.info("PersistentContextProvider: no records for customer '%s'; query='%s'.", customer_id, (query_text or "<none>"))
            return Context()

        logger.info("PersistentContextProvider: returning %d stored record(s) for customer '%s'.", len(records), customer_id)

        formatted = [
            f"- [{record.issue_category}] {record.summary} ({record.created_at.astimezone(AEST_TZ).strftime('%d/%m/%y %H:%M AEST')})"
            for record in records
        ]

        instructions = (
            "Consider the following recent complaints from persistent memory:\n"
            + "\n".join(formatted)
        )

        return Context(instructions=instructions)

def _extract_user_text(messages: Any) -> str | None:
    if isinstance(messages, ChatMessage):
        role_value = getattr(messages.role, "value", None)
        if role_value == "user":
            return messages.text
        return None

    if isinstance(messages, str):
        return messages

    if isinstance(messages, (list, tuple)):
        for item in reversed(messages):
            text = _extract_user_text(item)
            if text:
                return text
    return None

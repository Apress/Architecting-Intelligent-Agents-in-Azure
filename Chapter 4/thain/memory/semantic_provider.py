from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from agent_framework import ChatMessage, Context, ContextProvider

from memory.semantic_service import SemanticRecallService, SemanticSearchError

logger = logging.getLogger(__name__)
AEST_TZ = timezone(timedelta(hours=10))


class SemanticContextProvider(ContextProvider):
    """Context provider that surfaces semantically similar complaints from Azure AI Search."""

    def __init__(
        self,
        *,
        service: SemanticRecallService,
        customer_id: str,
        lookup_limit: int = 3,
        mode: str = "semantic",
    ) -> None:
        self._service = service
        self._customer_id = customer_id
        self._lookup_limit = lookup_limit
        self._mode = mode

    async def invoking(self, messages: Any, **kwargs: Any) -> Context:  # type: ignore[override]
        if self._mode != "semantic":
            logger.info("SemanticContextProvider: semantic recall disabled (mode=%s).", self._mode)
            return Context()

        query_text = _extract_user_text(messages)
        if not query_text:
            return Context()

        try:
            records = await self._service.find_similar(
                customer_id=self._customer_id,
                text=query_text,
                category=None,
                top_k=self._lookup_limit,
            )
        except SemanticSearchError:
            logger.debug("Semantic recall unavailable; continuing without semantic context.", exc_info=True)
            return Context()

        if not records:
            logger.info("SemanticContextProvider: no semantic matches for query '%s'.", query_text[:80])
            return Context()

        top = records[0]
        logger.info(
            "SemanticContextProvider: surfaced %d semantic match(es); top summary='%s'.",
            len(records),
            top.get('summary', '(no summary)'),
        )

        formatted = []
        for record in records:
            created_at = record.get("createdAt")
            if isinstance(created_at, datetime):
                timestamp = created_at.astimezone(AEST_TZ).strftime("%d/%m/%y %H:%M AEST")
            else:
                timestamp = str(created_at or "unknown time")
            formatted.append(
                f"- [{record.get('issueCategory','Unknown')} at {timestamp}] {record.get('summary','(no summary)')}"
            )

        instructions = "Consider related complaints found via semantic recall:\n" + "\n".join(formatted)
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

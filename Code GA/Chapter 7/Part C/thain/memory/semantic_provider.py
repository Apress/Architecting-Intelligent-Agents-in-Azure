from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from agent_framework import ContextProvider, SessionContext

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
        super().__init__(source_id="semantic-recall")
        self._service = service
        self._customer_id = customer_id
        self._lookup_limit = lookup_limit
        self._mode = mode

    async def before_run(self, *, agent: Any, session: Any, context: SessionContext, state: dict) -> None:
        if self._mode not in {"semantic", "agentic"}:
            logger.info("SemanticContextProvider: semantic recall disabled (mode=%s).", self._mode)
            return

        query_text: str | None = None
        for msg in reversed(context.input_messages):
            if msg.role == "user" and msg.text:
                query_text = msg.text
                break

        if not query_text:
            return

        try:
            records = await self._service.find_similar(
                customer_id=self._customer_id,
                text=query_text,
                category=None,
                top_k=self._lookup_limit,
            )
        except SemanticSearchError:
            logger.debug("Semantic recall unavailable; continuing without semantic context.", exc_info=True)
            return

        if not records:
            logger.info("SemanticContextProvider: no semantic matches for query '%s'.", query_text[:80])
            return

        top = records[0]
        logger.info(
            "SemanticContextProvider: surfaced %d semantic match(es); top summary='%s'.",
            len(records),
            top.get("summary", "(no summary)"),
        )

        formatted = []
        for record in records:
            created_at = record.get("createdAt")
            if isinstance(created_at, datetime):
                timestamp = created_at.astimezone(AEST_TZ).strftime("%d/%m/%y %H:%M AEST")
            else:
                timestamp = str(created_at or "unknown time")
            formatted.append(
                f"- [{record.get('issueCategory', 'Unknown')} at {timestamp}] {record.get('summary', '(no summary)')}"
            )

        instructions = "Consider related complaints found via semantic recall:\n" + "\n".join(formatted)
        context.instructions.append(instructions)

from __future__ import annotations

import logging
from typing import Any, Dict, Annotated

from agent_framework import tool

logger = logging.getLogger(__name__)


def create_search_tool(semantic_service, semantic_search_config):
    """Factory to build the agentic search tool bound to the current semantic service/config."""

    @tool(
        name="search_similar_complaints",
        description="Retrieve semantically similar past complaints using Azure AI Search embeddings.",
    )
    async def search_similar_complaints(
        customer_message: Annotated[str, "The latest customer message to match for similarity."],
        top_k: Annotated[int, "Maximum number of similar complaints to return."] = 3,
        category: Annotated[str | None, "Optional issue category filter."] = None,
        time_window_days: Annotated[int, "Restrict to complaints created within the last N days."] = 90,
        include_outcomes: Annotated[bool, "If true, include decision-grade metadata like ticket/notification/outcome."] = False,
    ) -> list[Dict[str, Any]]:
        if not semantic_service or not semantic_search_config:
            return []
        if semantic_search_config.mode != "agentic":
            return []

        try:
            k = max(1, top_k) if top_k else semantic_search_config.default_top_k
            results = await semantic_service.find_similar(
                customer_id=semantic_search_config.customer_id,
                text=customer_message,
                category=category,
                top_k=k,
                time_window_days=time_window_days,
                include_outcomes=include_outcomes,
            )
        except Exception as exc:  # avoid raising into the agent; surface empty
            logger.warning("Agentic search tool failed: %s", exc, exc_info=True)
            return [{"_trace_error": {"error_type": type(exc).__name__, "reason": "semantic_search_failed"}}]

        return results

    return search_similar_complaints


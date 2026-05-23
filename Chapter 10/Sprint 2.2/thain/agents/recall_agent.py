from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List

from orchestration.contracts import RecallResult


class RecallAgent:
    def __init__(
        self,
        search_tool: Callable[..., Any] | None,
        retrieval_mode: str,
        default_top_k: int = 3,
    ) -> None:
        self._search_tool = search_tool
        self._retrieval_mode = retrieval_mode
        self._default_top_k = max(1, default_top_k)

    async def run(self, message: str, category: str | None = None) -> RecallResult:
        if self._retrieval_mode == "off" or not self._search_tool:
            return RecallResult(matches=[], recency="none", retrieval_mode=self._retrieval_mode)

        results = await self._search_tool(
            customer_message=message,
            top_k=self._default_top_k,
            category=category,
            include_outcomes=self._retrieval_mode == "agentic",
        )
        matches = results if isinstance(results, list) else []
        recency = _recency_from_results(matches)
        return RecallResult(matches=matches, recency=recency, retrieval_mode=self._retrieval_mode)


def _recency_from_results(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "none"

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=30)
    for item in results:
        created_at = item.get("createdAt")
        if not created_at:
            continue
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed >= threshold:
            return "recent"
    return "stale"

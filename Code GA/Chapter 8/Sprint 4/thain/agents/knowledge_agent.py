from __future__ import annotations

from typing import Any, Callable, Dict, List

from orchestration.contracts import KnowledgeResult


class KnowledgeAgent:
    def __init__(self, retrieve_tool: Callable[..., Any] | None) -> None:
        self._retrieve_tool = retrieve_tool

    async def run(self, query: str) -> KnowledgeResult:
        if not self._retrieve_tool:
            return KnowledgeResult(docs=[])

        results = await self._retrieve_tool(query=query, top_k=3)
        docs = results if isinstance(results, list) else []
        return KnowledgeResult(docs=docs)

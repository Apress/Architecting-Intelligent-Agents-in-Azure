from __future__ import annotations

import logging
from typing import Any

from azure.core.credentials import TokenCredential

from config.settings import AzureAIDocsSearchConfig
from services.embedding import EmbeddingService

from .docs_search_client import AzureDocsSearchClient, DocsSearchError

logger = logging.getLogger(__name__)


class DocsRetrievalService:
    """Coordinates embedding generation and KB queries in Azure AI Search."""

    def __init__(
        self,
        config: AzureAIDocsSearchConfig,
        *,
        search_credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        self._search_client = AzureDocsSearchClient(config, credential=search_credential)
        self._embedding_service = EmbeddingService(
            endpoint=config.embedding_endpoint,
            deployment=config.embedding_deployment,
            api_version=config.embedding_api_version,
            api_key=config.embedding_api_key,
        )
        self._default_top_k = config.default_top_k

    async def close(self) -> None:
        await self._embedding_service.close()
        await self._search_client.close()

    async def retrieve(
        self,
        *,
        query: str,
        top_k: int | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            embedding = await self._embedding_service.embed(query)
            raw_results = await self._search_client.search_documents(
                query_text=query,
                embedding=embedding,
                top_k=top_k or self._default_top_k,
                tags=tags,
            )
            results: list[dict[str, Any]] = []
            for item in raw_results:
                snippet = str(item.get("snippet", "")).strip()
                if not snippet:
                    snippet = "No snippet available."
                mapped = {
                    "id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "snippet": snippet,
                    "url": str(item.get("url", "")),
                    "source": str(item.get("source", "kb")),
                    "tags": [str(tag) for tag in item.get("tags", []) if str(tag).strip()],
                }
                if item.get("score") is not None:
                    mapped["score"] = item["score"]
                results.append(mapped)
            return results
        except DocsSearchError:
            raise
        except Exception as exc:
            logger.warning("Docs retrieval failed: %s", exc, exc_info=True)
            raise DocsSearchError("Docs retrieval failed.") from exc

    async def index_documents(self, documents: list[dict[str, Any]]) -> int:
        indexed = 0
        for item in documents:
            text = str(item.get("content") or item.get("snippet") or item.get("title") or "").strip()
            if not text:
                continue
            embedding = await self._embedding_service.embed(text)
            await self._search_client.upsert_document(item, embedding)
            indexed += 1
        return indexed

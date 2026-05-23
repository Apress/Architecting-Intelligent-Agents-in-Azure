from __future__ import annotations

import logging
from typing import Any, List

from config.settings import AzureAISearchConfig
from models.complaint import ComplaintRecordModel
from services.embedding import EmbeddingService

from .search_client import AzureSemanticSearchClient, SemanticSearchError

logger = logging.getLogger(__name__)


class SemanticRecallService:
    """Coordinates embedding generation and Azure AI Search queries."""

    def __init__(self, config: AzureAISearchConfig) -> None:
        self._config = config
        self._search_client = AzureSemanticSearchClient(config)
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

    async def index_record(self, record: ComplaintRecordModel) -> None:
        """Store the complaint embedding inside Azure AI Search."""

        try:
            embedding = await self._embedding_service.embed(record.raw_message)
            await self._search_client.upsert_document(record, embedding)
        except SemanticSearchError:
            raise
        except Exception as exc:
            logger.warning("Failed to index complaint for semantic recall: %s", exc, exc_info=True)
            raise SemanticSearchError("Semantic indexing failed.") from exc

    async def find_similar(
        self,
        *,
        customer_id: str,
        text: str,
        category: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            embedding = await self._embedding_service.embed(text)
            return await self._search_client.search_similar(
                customer_id=customer_id,
                embedding=embedding,
                category=category,
                top_k=top_k or self._default_top_k,
            )
        except SemanticSearchError:
            raise
        except Exception as exc:
            logger.warning("Semantic search failed: %s", exc, exc_info=True)
            raise SemanticSearchError("Semantic search failed.") from exc

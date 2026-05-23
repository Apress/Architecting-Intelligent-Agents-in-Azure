from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List

from azure.core.credentials import TokenCredential

from config.settings import AzureAISearchConfig
from models.complaint import ComplaintRecordModel
from services.embedding import EmbeddingService

from .search_client import AzureSemanticSearchClient, SemanticSearchError

logger = logging.getLogger(__name__)


class SemanticRecallService:
    """Coordinates embedding generation and Azure AI Search queries."""

    def __init__(
        self,
        config: AzureAISearchConfig,
        *,
        search_credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        self._search_client = AzureSemanticSearchClient(config, credential=search_credential)
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
        time_window_days: int | None = None,
        include_outcomes: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            embedding = await self._embedding_service.embed(text)
            created_after = None
            if time_window_days and time_window_days > 0:
                created_after = datetime.now(timezone.utc) - timedelta(days=time_window_days)

            results = await self._search_client.search_similar(
                customer_id=customer_id,
                embedding=embedding,
                category=category,
                top_k=top_k or self._default_top_k,
                created_after=created_after,
            )

            if not include_outcomes:
                for item in results:
                    item.pop("ticketCreated", None)
                    item.pop("notifiedTeam", None)
                    item.pop("outcome", None)

            return results
        except SemanticSearchError:
            raise
        except Exception as exc:
            logger.warning("Semantic search failed: %s", exc, exc_info=True)
            raise SemanticSearchError("Semantic search failed.") from exc

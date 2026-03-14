from __future__ import annotations

import logging
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from config.settings import AzureAISearchConfig
from models.complaint import ComplaintRecordModel

logger = logging.getLogger(__name__)


class SemanticSearchError(RuntimeError):
    """Raised when the Azure AI Search layer is unavailable."""


class AzureSemanticSearchClient:
    """Manages Azure AI Search index creation and querying."""

    def __init__(self, config: AzureAISearchConfig) -> None:
        self._config = config
        self._index_name = config.index_name
        self._credential: AzureKeyCredential | DefaultAzureCredential
        if config.api_key:
            self._credential = AzureKeyCredential(config.api_key)
            self._aad_credential = None
        else:
            self._aad_credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            self._credential = self._aad_credential
        self._index_client = SearchIndexClient(endpoint=config.endpoint, credential=self._credential)
        self._search_client: SearchClient | None = None
        self._vector_dimensions: int | None = None

    async def close(self) -> None:
        if self._search_client:
            await self._search_client.close()
        await self._index_client.close()
        if isinstance(self._credential, DefaultAzureCredential):
            await self._credential.close()

    async def ensure_index(self, vector_dimensions: int) -> None:
        if self._search_client:
            return

        try:
            await self._index_client.get_index(self._index_name)
            self._vector_dimensions = vector_dimensions
            logger.debug("Using existing Azure AI Search index '%s'.", self._index_name)
        except Exception:
            logger.info("Creating Azure AI Search index '%s'.", self._index_name)
            await self._create_index(vector_dimensions)

        self._search_client = SearchClient(
            endpoint=self._config.endpoint,
            index_name=self._index_name,
            credential=self._credential,
        )

    async def _create_index(self, vector_dimensions: int) -> None:
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="customerId", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="issueCategory", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="summary"),
            SearchableField(name="rawMessage"),
            SimpleField(name="createdAt", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=vector_dimensions,
                vector_search_profile_name="thain-vector-profile",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(name="thain-hnsw"),
            ],
            profiles=[
                VectorSearchProfile(name="thain-vector-profile", algorithm_configuration_name="thain-hnsw"),
            ],
        )

        index = SearchIndex(name=self._index_name, fields=fields, vector_search=vector_search)
        await self._index_client.create_index(index)
        self._vector_dimensions = vector_dimensions

    async def upsert_document(self, record: ComplaintRecordModel, embedding: list[float]) -> None:
        if not self._search_client or not self._vector_dimensions:
            await self.ensure_index(len(embedding))
        if not self._search_client:
            raise SemanticSearchError("Search client unavailable.")

        document = {
            "id": record.id,
            "customerId": record.customer_id,
            "issueCategory": record.issue_category,
            "summary": record.summary,
            "rawMessage": record.raw_message,
            "createdAt": record.created_at,
            "vector": embedding,
        }

        try:
            await self._search_client.upload_documents(documents=[document])
        except Exception as exc:
            logger.warning("Failed to upsert document into Azure AI Search: %s", exc)
            raise SemanticSearchError("Unable to upsert search document.") from exc

    async def search_similar(
        self,
        *,
        customer_id: str,
        embedding: list[float],
        category: str | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        if not self._search_client or not self._vector_dimensions:
            await self.ensure_index(len(embedding))
        if not self._search_client:
            raise SemanticSearchError("Search client unavailable.")

        filter_expression = None
        if category:
            sanitized_category = category.replace("'", "''")
            filter_expression = f"issueCategory eq '{sanitized_category}'"

        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=top_k,
            fields="vector",
            kind="vector",
        )

        try:
            results_iter = await self._search_client.search(
                search_text="",
                filter=filter_expression,
                vector_queries=[vector_query],
                select=["id", "customerId", "issueCategory", "summary", "rawMessage", "createdAt"],
                top=top_k,
            )
            results: list[dict[str, Any]] = []
            async for doc in results_iter:
                results.append(
                    {
                        "id": doc["id"],
                        "customerId": doc.get("customerId", ""),
                        "issueCategory": doc.get("issueCategory", ""),
                        "summary": doc.get("summary", ""),
                        "rawMessage": doc.get("rawMessage", ""),
                        "createdAt": doc.get("createdAt"),
                    }
                )
            return results
        except Exception as exc:
            logger.warning("Failed to query Azure AI Search: %s", exc)
            raise SemanticSearchError("Unable to query search index.") from exc

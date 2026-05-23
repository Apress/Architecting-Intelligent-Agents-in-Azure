from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from azure.core.credentials import AzureKeyCredential, TokenCredential
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

from config.settings import AzureAIDocsSearchConfig

logger = logging.getLogger(__name__)


class DocsSearchError(RuntimeError):
    """Raised when the Azure AI Search KB layer is unavailable."""


class AzureDocsSearchClient:
    """Manages Azure AI Search KB index creation and querying."""

    def __init__(
        self,
        config: AzureAIDocsSearchConfig,
        credential: TokenCredential | None = None,
    ) -> None:
        self._config = config
        self._index_name = config.index_name
        self._credential: AzureKeyCredential | DefaultAzureCredential
        if config.api_key:
            self._credential = AzureKeyCredential(config.api_key)
            self._aad_credential = None
        else:
            self._aad_credential = credential or DefaultAzureCredential(exclude_interactive_browser_credential=False)
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
            logger.debug("Using existing docs search index '%s'.", self._index_name)
        except Exception:
            logger.info("Creating docs search index '%s'.", self._index_name)
            await self._create_index(vector_dimensions)

        self._search_client = SearchClient(
            endpoint=self._config.endpoint,
            index_name=self._index_name,
            credential=self._credential,
        )

    async def _create_index(self, vector_dimensions: int) -> None:
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="docType", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="title"),
            SearchableField(name="content"),
            SearchableField(name="snippet"),
            SimpleField(name="url", type=SearchFieldDataType.String),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchField(
                name="tags",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                searchable=True,
                filterable=True,
                facetable=True,
            ),
            SimpleField(name="updatedAt", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=vector_dimensions,
                vector_search_profile_name="thain-docs-vector-profile",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="thain-docs-hnsw")],
            profiles=[
                VectorSearchProfile(
                    name="thain-docs-vector-profile",
                    algorithm_configuration_name="thain-docs-hnsw",
                )
            ],
        )

        index = SearchIndex(name=self._index_name, fields=fields, vector_search=vector_search)
        await self._index_client.create_index(index)
        self._vector_dimensions = vector_dimensions

    async def upsert_document(self, document: dict[str, Any], embedding: list[float]) -> None:
        if not self._search_client or not self._vector_dimensions:
            await self.ensure_index(len(embedding))
        if not self._search_client:
            raise DocsSearchError("Search client unavailable.")

        payload = {
            "id": str(document.get("id", "")),
            "docType": str(document.get("docType", "kb")),
            "title": str(document.get("title", "")),
            "content": str(document.get("content", "")),
            "snippet": str(document.get("snippet", "")),
            "url": str(document.get("url", "")),
            "source": str(document.get("source", "kb")),
            "tags": [str(tag) for tag in document.get("tags", []) if str(tag).strip()],
            "updatedAt": document.get("updatedAt") or datetime.now(timezone.utc),
            "vector": embedding,
        }

        try:
            await self._search_client.upload_documents(documents=[payload])
        except Exception as exc:
            logger.warning("Failed to upsert KB document into Azure AI Search: %s", exc)
            raise DocsSearchError("Unable to upsert KB document.") from exc

    async def search_documents(
        self,
        *,
        query_text: str,
        embedding: list[float],
        top_k: int = 3,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._search_client:
            self._search_client = SearchClient(
                endpoint=self._config.endpoint,
                index_name=self._index_name,
                credential=self._credential,
            )

        filters: list[str] = ["docType eq 'kb'"]
        if tags:
            sanitized = [tag.replace("'", "''") for tag in tags if tag.strip()]
            if sanitized:
                tag_filter = " or ".join([f"tags/any(t: t eq '{tag}')" for tag in sanitized])
                filters.append(f"({tag_filter})")
        filter_expression = " and ".join(filters) if filters else None

        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=max(1, top_k),
            fields="vector",
            kind="vector",
        )

        try:
            results_iter = await self._search_client.search(
                search_text=query_text or "*",
                filter=filter_expression,
                vector_queries=[vector_query],
                select=["id", "title", "content", "snippet", "url", "source", "tags", "updatedAt"],
                top=max(1, top_k),
            )
            results: list[dict[str, Any]] = []
            async for doc in results_iter:
                result = {
                    "id": doc.get("id", ""),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    "snippet": doc.get("snippet", ""),
                    "url": doc.get("url", ""),
                    "source": doc.get("source", "kb"),
                    "tags": doc.get("tags") or [],
                }
                if "@search.score" in doc:
                    result["score"] = doc.get("@search.score")
                results.append(result)
            return results
        except Exception as exc:
            logger.warning("Failed to query KB index from Azure AI Search: %s", exc)
            raise DocsSearchError("Unable to query KB index.") from exc

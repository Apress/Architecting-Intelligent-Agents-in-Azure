from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
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
from services.reliability import execute_dependency_call

logger = logging.getLogger(__name__)


class SemanticSearchError(RuntimeError):
    """Raised when the Azure AI Search layer is unavailable."""


class AzureSemanticSearchClient:
    """Manages Azure AI Search index creation and querying."""

    def __init__(
        self,
        config: AzureAISearchConfig,
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
            # Metadata reads require index-admin permissions that runtime MI may not have.
            # Do a direct check so 401/403 does not poison shared search reliability state.
            await self._index_client.get_index(self._index_name)
            self._vector_dimensions = vector_dimensions
            logger.debug("Using existing Azure AI Search index '%s'.", self._index_name)
        except ResourceNotFoundError:
            logger.info("Creating Azure AI Search index '%s'.", self._index_name)
            await self._create_index(vector_dimensions)
        except HttpResponseError as exc:
            # Runtime MI can query documents without index-admin metadata permissions.
            # If metadata read is forbidden, continue and use the existing index.
            if getattr(exc, "status_code", None) in {401, 403}:
                self._vector_dimensions = vector_dimensions
                logger.debug(
                    "Skipping metadata check for index '%s' due to auth scope (status=%s).",
                    self._index_name,
                    getattr(exc, "status_code", "unknown"),
                )
            else:
                logger.warning("Failed to check Azure AI Search index '%s': %s", self._index_name, exc, exc_info=True)
                raise SemanticSearchError("Unable to access search index metadata.") from exc
        except Exception as exc:
            logger.warning("Failed to check Azure AI Search index '%s': %s", self._index_name, exc, exc_info=True)
            raise SemanticSearchError("Unable to access search index metadata.") from exc

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
            SimpleField(name="ticketCreated", type=SearchFieldDataType.Boolean, filterable=True),
            SimpleField(name="notifiedTeam", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="outcome"),
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
        await execute_dependency_call(
            "search",
            "search.index.create",
            lambda: self._index_client.create_index(index),
        )
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
            "ticketCreated": record.ticket_created,
            "notifiedTeam": record.notified_team,
            "outcome": record.outcome,
            "vector": embedding,
        }

        try:
            await execute_dependency_call(
                "search",
                "search.documents.upload",
                lambda: self._search_client.upload_documents(documents=[document]),
            )
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
        created_after: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        if not self._search_client or not self._vector_dimensions:
            await self.ensure_index(len(embedding))
        if not self._search_client:
            raise SemanticSearchError("Search client unavailable.")

        filters = []
        if category:
            sanitized_category = category.replace("'", "''")
            filters.append(f"issueCategory eq '{sanitized_category}'")
        if created_after:
            dt = created_after
            if created_after.tzinfo is None:
                dt = created_after.replace(tzinfo=timezone.utc)
            else:
                dt = created_after.astimezone(timezone.utc)
            filters.append(f"createdAt ge {dt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        filter_expression = " and ".join(filters) if filters else None

        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=top_k,
            fields="vector",
            kind="vector",
        )

        try:
            async def _query_search() -> list[dict[str, Any]]:
                results_iter = await self._search_client.search(
                    search_text="",
                    filter=filter_expression,
                    vector_queries=[vector_query],
                    select=[
                        "id",
                        "customerId",
                        "issueCategory",
                        "summary",
                        "rawMessage",
                        "createdAt",
                        "ticketCreated",
                        "notifiedTeam",
                        "outcome",
                    ],
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
                            "ticketCreated": doc.get("ticketCreated", False),
                            "notifiedTeam": doc.get("notifiedTeam"),
                            "outcome": doc.get("outcome"),
                        }
                    )
                return results

            return await execute_dependency_call(
                "search",
                "search.documents.vector_query",
                _query_search,
            )
        except Exception as exc:
            logger.warning("Failed to query Azure AI Search: %s", exc)
            raise SemanticSearchError("Unable to query search index.") from exc



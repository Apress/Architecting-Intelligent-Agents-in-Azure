import unittest
from unittest.mock import AsyncMock, patch

from config.settings import AzureAIDocsSearchConfig
from memory.docs_service import DocsRetrievalService


class DocsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_maps_results(self) -> None:
        config = AzureAIDocsSearchConfig(
            endpoint="https://example.search.windows.net",
            index_name="kb-index",
            api_key="search-key",
            embedding_endpoint="https://example.openai.azure.com",
            embedding_deployment="text-embedding-3-large",
            embedding_api_key="embed-key",
        )

        with patch("memory.docs_service.EmbeddingService") as embedding_cls, patch(
            "memory.docs_service.AzureDocsSearchClient"
        ) as search_cls:
            embedding = embedding_cls.return_value
            embedding.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
            embedding.close = AsyncMock()

            search = search_cls.return_value
            search.search_documents = AsyncMock(
                return_value=[
                    {
                        "id": "doc-1",
                        "title": "Wi-Fi Guide",
                        "snippet": "",
                        "url": "https://kb/doc-1",
                        "source": "kb",
                        "tags": ["wifi"],
                        "score": 1.2,
                    }
                ]
            )
            search.close = AsyncMock()

            service = DocsRetrievalService(config)
            result = await service.retrieve(query="wifi drops", top_k=2)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], "doc-1")
            self.assertEqual(result[0]["snippet"], "No snippet available.")
            self.assertEqual(result[0]["score"], 1.2)
            await service.close()


if __name__ == "__main__":
    unittest.main()

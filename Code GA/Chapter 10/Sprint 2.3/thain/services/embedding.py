from __future__ import annotations

import logging
from typing import Any, Sequence

from services.reliability import execute_dependency_call

try:
    from openai import AsyncAzureOpenAI
except ImportError:  # pragma: no cover - dependency missing
    AsyncAzureOpenAI = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Thin wrapper around Azure OpenAI embeddings via the OpenAI SDK."""

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str,
        api_key: str | None = None,
    ) -> None:
        if AsyncAzureOpenAI is None:
            raise RuntimeError("The openai package is required for embeddings. Install openai>=1.0.")
        if not api_key:
            raise RuntimeError("An embedding API key is required when using the OpenAI SDK path.")

        self._deployment = deployment
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the provided text."""
        async def _call_embeddings() -> Any:
            return await self._client.embeddings.create(model=self._deployment, input=text)

        response = await execute_dependency_call(
            "openai",
            "embeddings.create",
            _call_embeddings,
        )
        vector: Sequence[float] = response.data[0].embedding
        return list(vector)

    async def close(self) -> None:
        close_method = getattr(self._client, "close", None)
        if callable(close_method):
            maybe_await = close_method()
            if hasattr(maybe_await, "__await__"):
                await maybe_await

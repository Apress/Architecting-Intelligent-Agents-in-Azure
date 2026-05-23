from __future__ import annotations

import asyncio
import dataclasses
import inspect
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import MissingConfigError, load_auth_mode, load_docs_search_config
from memory.docs_service import DocsRetrievalService


TEST_CASES: list[tuple[str, str]] = [
    ("Wi-Fi keeps dropping across two branches. Need procedure.", "wifi"),
    ("What is the escalation policy for recurring network outages?", "escalation"),
    ("Sensor calibration drift is causing disruptions. Need a guide.", "sensor"),
]


async def _close_if_supported(target: Any) -> None:
    close_method = getattr(target, "close", None)
    if not callable(close_method):
        return
    maybe_await = close_method()
    if inspect.isawaitable(maybe_await):
        await maybe_await


def _contains_token(results: list[dict[str, Any]], token: str) -> bool:
    token_l = token.lower()
    for item in results:
        text = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("snippet", "")),
                " ".join([str(tag) for tag in item.get("tags", [])]),
            ]
        ).lower()
        if token_l in text:
            return True
    return False


async def _run() -> None:
    auth_mode = load_auth_mode()
    docs_config = load_docs_search_config()
    if not docs_config:
        raise MissingConfigError(
            "Docs search config is missing. Set AZURE_SEARCH_ENDPOINT, "
            "AZURE_SEARCH_DOCS_INDEX_NAME, AZURE_OPENAI_EMBEDDING_ENDPOINT, "
            "and AZURE_OPENAI_EMBEDDING_DEPLOYMENT."
        )

    if not docs_config.embedding_api_key:
        if auth_mode == "managed_identity":
            vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
            secret_name = os.getenv("KV_EMBEDDING_API_KEY_NAME", "").strip()
            if not vault_uri or not secret_name:
                raise MissingConfigError(
                    "Missing embedding API key in managed identity mode. "
                    "Set KEY_VAULT_URI and KV_EMBEDDING_API_KEY_NAME."
                )
            try:
                from azure.identity import DefaultAzureCredential
                from azure.keyvault.secrets import SecretClient
            except ImportError as exc:
                raise MissingConfigError(
                    "azure-keyvault-secrets is required for managed identity embedding keys."
                ) from exc
            sync_credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_uri, credential=sync_credential)
            embedding_key = client.get_secret(secret_name).value
            if not embedding_key:
                raise MissingConfigError(
                    "Missing embedding API key in managed identity mode. "
                    "Set KEY_VAULT_URI and KV_EMBEDDING_API_KEY_NAME."
                )
            docs_config = dataclasses.replace(docs_config, embedding_api_key=embedding_key)
        else:
            raise MissingConfigError(
                "Missing embedding API key. Set AZURE_OPENAI_EMBEDDING_API_KEY for local auth."
            )

    async_credential = None
    if auth_mode == "managed_identity":
        from azure.identity.aio import DefaultAzureCredential

        async_credential = DefaultAzureCredential()

    service = DocsRetrievalService(docs_config, search_credential=async_credential)
    try:
        for query, token in TEST_CASES:
            first = await service.retrieve(query=query, top_k=3)
            second = await service.retrieve(query=query, top_k=3)
            if not first:
                raise RuntimeError(f"No retrieval results for query: {query}")
            if not second:
                raise RuntimeError(f"Second retrieval returned no results for query: {query}")

            first_top = str(first[0].get("id", "")).strip()
            second_top = str(second[0].get("id", "")).strip()
            if first_top and second_top and first_top != second_top:
                raise RuntimeError(
                    "Retrieval top result not stable across repeated queries. "
                    f"Query='{query}' first='{first_top}' second='{second_top}'"
                )

            if not _contains_token(first, token):
                raise RuntimeError(
                    f"Expected token '{token}' was not present in top results for query: {query}"
                )

            print(f"OK: query='{query}' top_id='{first_top or 'n/a'}' hits={len(first)}")
    finally:
        await service.close()
        await _close_if_supported(async_credential)


def main() -> int:
    asyncio.run(_run())
    print("Retrieval validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

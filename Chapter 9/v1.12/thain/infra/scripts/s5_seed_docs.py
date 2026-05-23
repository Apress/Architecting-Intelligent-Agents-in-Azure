from __future__ import annotations

import argparse
import asyncio
import dataclasses
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import MissingConfigError, load_auth_mode, load_docs_search_config
from memory.docs_service import DocsRetrievalService


def _load_documents(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of documents.")

    docs: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not str(item.get("id", "")).strip():
            continue
        docs.append(item)
    return docs


async def _close_if_supported(target: Any) -> None:
    close_method = getattr(target, "close", None)
    if not callable(close_method):
        return
    maybe_await = close_method()
    if inspect.isawaitable(maybe_await):
        await maybe_await


async def _run(data_file: Path) -> int:
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

    documents = _load_documents(data_file)
    if not documents:
        raise ValueError(f"No valid documents found in {data_file}.")

    async_credential = None
    if auth_mode == "managed_identity":
        from azure.identity.aio import DefaultAzureCredential

        async_credential = DefaultAzureCredential()

    service = DocsRetrievalService(docs_config, search_credential=async_credential)
    try:
        indexed = await service.index_documents(documents)
    finally:
        await service.close()
        await _close_if_supported(async_credential)
    return indexed


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Sprint 5 KB docs into Azure AI Search.")
    parser.add_argument(
        "--data-file",
        default=str(ROOT / "infra" / "data" / "s5-kb-documents.json"),
        help="Path to JSON document array for KB seeding.",
    )
    args = parser.parse_args()
    data_file = Path(args.data_file).resolve()
    if not data_file.exists():
        raise FileNotFoundError(f"Seed data file not found: {data_file}")

    indexed = asyncio.run(_run(data_file))
    print(f"Indexed documents: {indexed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

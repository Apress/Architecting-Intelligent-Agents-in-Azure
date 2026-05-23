from __future__ import annotations

import logging
from typing import Optional

from azure.identity import AzureCliCredential as SyncAzureCliCredential
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)


def get_azure_credential(auth_mode: str, *, async_credential: bool = True):
    if async_credential:
        if auth_mode == "managed_identity":
            return DefaultAzureCredential()
        return AzureCliCredential()
    if auth_mode == "managed_identity":
        return SyncDefaultAzureCredential()
    return SyncAzureCliCredential()


def get_key_vault_client(vault_uri: str, credential) -> SecretClient:
    return SecretClient(vault_url=vault_uri, credential=credential)


def get_key_vault_secret(
    *,
    vault_uri: str,
    credential,
    name: str,
) -> Optional[str]:
    if not vault_uri or not name:
        return None
    try:
        client = get_key_vault_client(vault_uri, credential)
        return client.get_secret(name).value
    except Exception as exc:
        logger.warning("Failed to fetch secret '%s' from Key Vault: %s", name, exc)
        return None

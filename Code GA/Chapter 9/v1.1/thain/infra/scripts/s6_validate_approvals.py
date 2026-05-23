from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential


def _get_auth_mode() -> str:
    raw = os.getenv("THAIN_AUTH_MODE", "local").strip().lower()
    if raw in {"managed_identity", "managed-identity", "mi", "azure"}:
        return "managed_identity"
    return "local"


async def _get_container() -> Any:
    endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
    database = os.getenv("COSMOS_DATABASE", "").strip()
    container_name = os.getenv("APPROVALS_CONTAINER", "").strip()
    if not endpoint or not database or not container_name:
        raise RuntimeError("Missing COSMOS_ENDPOINT/COSMOS_DATABASE/APPROVALS_CONTAINER.")

    key = os.getenv("COSMOS_KEY", "").strip()
    auth_mode = _get_auth_mode()
    credential = None
    if key:
        client = CosmosClient(endpoint, credential=key)
    else:
        credential = DefaultAzureCredential() if auth_mode == "managed_identity" else AzureCliCredential()
        client = CosmosClient(endpoint, credential=credential)

    database_client = client.get_database_client(database)
    return client, credential, database_client.get_container_client(container_name)


async def _find_by_trace(container, trace_id: str) -> dict[str, Any] | None:
    query = "SELECT * FROM c WHERE c.trace_id = @trace_id ORDER BY c.requested_at DESC"
    params = [{"name": "@trace_id", "value": trace_id}]
    items = container.query_items(query=query, parameters=params)
    async for item in items:
        return item
    return None


async def _read_by_id(container, approval_id: str) -> dict[str, Any] | None:
    try:
        return await container.read_item(item=approval_id, partition_key=approval_id)
    except Exception:
        return None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id")
    parser.add_argument("--approval-id")
    parser.add_argument("--wait-seconds", type=int, default=120)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--wait-for-execution", action="store_true")
    args = parser.parse_args()

    if not args.trace_id and not args.approval_id:
        print(json.dumps({"error": "trace_id or approval_id is required"}))
        return 1

    client, credential, container = await _get_container()
    try:
        record = None
        if args.trace_id:
            record = await _find_by_trace(container, args.trace_id)
        if not record and args.approval_id:
            record = await _read_by_id(container, args.approval_id)
        if not record:
            print(json.dumps({"error": "approval record not found"}))
            return 1

        approval_id = record.get("approval_id")
        status = str(record.get("status") or "pending")
        execution_status = str(record.get("execution_status") or "")
        deadline = time.monotonic() + max(args.wait_seconds, 0)

        while time.monotonic() < deadline:
            if args.wait_for_execution:
                if execution_status == "executed" or status in {"denied", "expired"}:
                    break
            else:
                if status in {"approved", "denied", "expired", "executed"}:
                    break
            await asyncio.sleep(max(args.poll_interval, 1))
            record = await _read_by_id(container, approval_id)
            if not record:
                break
            status = str(record.get("status") or "pending")
            execution_status = str(record.get("execution_status") or "")

        output = {
            "approval_id": approval_id,
            "status": status,
            "approved": record.get("approved") if record else None,
            "decision": record.get("decision") if record else None,
            "decided_at": record.get("decided_at") if record else None,
            "execution_status": record.get("execution_status") if record else None,
        }
        print(json.dumps(output))
        if args.wait_for_execution:
            if execution_status == "executed" or status in {"denied", "expired"}:
                return 0
            return 2
        if status in {"approved", "denied", "expired", "executed"}:
            return 0
        return 2
    finally:
        await client.close()
        if credential:
            await credential.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

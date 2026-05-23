from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import request

from config.settings import ApprovalWorkflowConfig
from services.approval_store import ApprovalStoreError, CosmosApprovalStore

logger = logging.getLogger(__name__)


def requires_approval(tool_type: str, enabled: bool) -> bool:
    return enabled and tool_type == "write"


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _new_approval_id() -> str:
    stamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    suffix = random.randint(100, 999)
    return f"APR-{stamp}-{suffix}"


@dataclass(frozen=True)
class ApprovalOutcome:
    approval_id: str
    tool_name: str
    approved: bool
    status: str
    reason: str | None = None
    expires_at: str | None = None
    decided_at: str | None = None
    tool_args_hash: str | None = None


class ApprovalService:
    def __init__(
        self,
        *,
        enabled: bool,
        store: CosmosApprovalStore | None = None,
        workflow: ApprovalWorkflowConfig | None = None,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._enabled = enabled
        self._store = store
        self._workflow = workflow
        self._on_request = on_request
        self._on_decision = on_decision
        self._context: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def with_context(
        self,
        *,
        trace_id: str,
        run_id: str,
        turn_id: str,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
    ) -> "ApprovalService":
        service = ApprovalService(
            enabled=self._enabled,
            store=self._store,
            workflow=self._workflow,
            on_request=on_request or self._on_request,
            on_decision=on_decision or self._on_decision,
        )
        service._context = {"trace_id": trace_id, "run_id": run_id, "turn_id": turn_id}
        return service

    async def request_approval(self, tool_name: str, payload: dict[str, Any]) -> ApprovalOutcome:
        if not self._enabled:
            return ApprovalOutcome(
                approval_id="local-approval",
                tool_name=tool_name,
                approved=True,
                status="approved",
                reason="approvals_disabled",
            )

        if not self._store or not self._workflow:
            logger.error("Approval service missing store or workflow configuration.")
            return ApprovalOutcome(
                approval_id="missing-config",
                tool_name=tool_name,
                approved=False,
                status="denied",
                reason="approval_config_missing",
            )

        approval_id = _new_approval_id()
        tool_args_hash = _hash_payload(payload)
        requested_at = datetime.now(timezone.utc)
        expires_at = requested_at.timestamp() + self._workflow.expires_seconds
        expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
        requested_by = payload.get("customer_id") or "unknown"

        record = {
            "approval_id": approval_id,
            "tool_name": tool_name,
            "tool_args_hash": tool_args_hash,
            "tool_args": payload,
            "requested_at": requested_at.isoformat(),
            "expires_at": expires_at_iso,
            "requested_by": requested_by,
            "trace_id": self._context.get("trace_id"),
            "run_id": self._context.get("run_id"),
            "turn_id": self._context.get("turn_id"),
            "status": "pending",
            "execution_status": "pending",
        }

        try:
            await self._store.create_request(record)
        except ApprovalStoreError:
            return ApprovalOutcome(
                approval_id=approval_id,
                tool_name=tool_name,
                approved=False,
                status="denied",
                reason="approval_store_error",
                tool_args_hash=tool_args_hash,
            )

        if self._on_request:
            self._on_request(
                {
                    "approval_id": approval_id,
                    "tool_name": tool_name,
                    "status": "pending",
                    "requested_at": record["requested_at"],
                    "expires_at": expires_at_iso,
                    "approvals_group": self._workflow.approvals_group,
                    "trace_id": record.get("trace_id"),
                    "run_id": record.get("run_id"),
                    "turn_id": record.get("turn_id"),
                    "tool_args_hash": tool_args_hash,
                }
            )

        try:
            await self._send_workflow_request(approval_id, tool_name, payload, tool_args_hash, expires_at_iso)
        except Exception as exc:
            logger.warning("Approval workflow request failed: %s", exc, exc_info=True)
            if self._store:
                await self._store.record_decision(
                    approval_id,
                    decision="denied",
                    decided_by="system",
                    decision_source="workflow_error",
                    decided_at=datetime.now(timezone.utc).isoformat(),
                )
            return ApprovalOutcome(
                approval_id=approval_id,
                tool_name=tool_name,
                approved=False,
                status="denied",
                reason="approval_request_failed",
                expires_at=expires_at_iso,
                tool_args_hash=tool_args_hash,
            )

        return ApprovalOutcome(
            approval_id=approval_id,
            tool_name=tool_name,
            approved=False,
            status="pending",
            reason="approval_pending",
            expires_at=expires_at_iso,
            tool_args_hash=tool_args_hash,
        )

    async def _send_workflow_request(
        self,
        approval_id: str,
        tool_name: str,
        payload: dict[str, Any],
        tool_args_hash: str,
        expires_at: str,
    ) -> None:
        workflow_url = self._workflow.logic_app_url if self._workflow else None
        if not workflow_url:
            return

        body = {
            "approval_id": approval_id,
            "tool_name": tool_name,
            "tool_args": payload,
            "tool_args_hash": tool_args_hash,
            "approvals_group": self._workflow.approvals_group,
            "trace_id": self._context.get("trace_id"),
            "run_id": self._context.get("run_id"),
            "turn_id": self._context.get("turn_id"),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "callback_url": self._workflow.callback_url,
            "callback_token": self._workflow.callback_secret,
        }

        await asyncio.to_thread(self._post_json, workflow_url, body)

    def _post_json(self, url: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as _:
            return None

    async def _poll_for_decision(self, approval_id: str, expires_at: str) -> dict[str, Any] | None:
        if not self._store or not self._workflow:
            return None

        deadline = time.monotonic() + self._workflow.timeout_seconds
        delay = max(self._workflow.poll_interval_seconds, 1)
        max_delay = max(self._workflow.max_poll_interval_seconds, delay)

        while time.monotonic() < deadline:
            record = await self._store.get(approval_id)
            if record:
                status = str(record.get("status") or "pending")
                if status in {"approved", "denied", "expired", "executed"}:
                    record["reason"] = record.get("decision") or status
                    return record

                if expires_at:
                    try:
                        expires_at_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    except ValueError:
                        expires_at_dt = None
                    if expires_at_dt and datetime.now(timezone.utc) > expires_at_dt:
                        expired = await self._store.record_decision(
                            approval_id,
                            decision="expired",
                            decided_by="system",
                            decision_source="system",
                            decided_at=datetime.now(timezone.utc).isoformat(),
                        )
                        if expired:
                            expired["reason"] = "expired"
                        return expired

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

        return None

    async def try_mark_executed(self, approval_id: str, executor_run_id: str | None = None) -> bool:
        if not self._store:
            return True
        if not executor_run_id:
            executor_run_id = self._context.get("run_id")
        return await self._store.mark_executed(approval_id, executor_run_id)

from __future__ import annotations

import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from api.schemas import (
    ApprovalCallbackRequest,
    ApprovalStatusResponse,
    ChatRequest,
    ChatResponse,
    FeedbackCreate,
    FeedbackResponse,
    FeedbackSummary,
)
from config.credentials import get_azure_credential, get_key_vault_secret
from config.settings import (
    MissingConfigError,
    load_approval_store_config,
    load_approval_workflow_config,
    load_auth_mode,
    load_feedback_config,
    load_feedback_enabled,
)
from main import load_config, run_thain_text_async  # type: ignore
from observability.trace_ids import new_run_id, new_trace_id, new_turn_id
from observability.trace_sinks import AppInsightsTraceSink
from observability.tracing import TraceRecorder
from services.approval_store import CosmosApprovalStore
from services.feedback_store import FeedbackStore


app = FastAPI(title="Thain API", version="0.1")
logger = logging.getLogger("thain.api")
AUTH_MODE = load_auth_mode()
SYNC_AZURE_CREDENTIAL = get_azure_credential(AUTH_MODE, async_credential=False)
_approval_store_config = load_approval_store_config()
_approval_workflow_config = load_approval_workflow_config()
_approval_store = (
    CosmosApprovalStore(_approval_store_config, credential=SYNC_AZURE_CREDENTIAL)
    if _approval_store_config
    else None
)
_feedback_enabled = load_feedback_enabled()
_feedback_config = load_feedback_config() if _feedback_enabled else None
_feedback_store = (
    FeedbackStore(_feedback_config, credential=SYNC_AZURE_CREDENTIAL)
    if _feedback_config
    else None
)
_callback_secret = None
if _approval_workflow_config:
    _callback_secret = _approval_workflow_config.callback_secret
    if AUTH_MODE == "managed_identity" and not _callback_secret and _approval_workflow_config.callback_secret_name:
        key_vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
        if key_vault_uri:
            _callback_secret = get_key_vault_secret(
                vault_uri=key_vault_uri,
                credential=SYNC_AZURE_CREDENTIAL,
                name=_approval_workflow_config.callback_secret_name,
            )


async def run_turn_http(message: str) -> ChatResponse:
    try:
        # Keep API calls on FastAPI's running event loop.
        text, trace_id = await run_thain_text_async(message, config=load_config())
    except MissingConfigError as exc:
        logger.error("Missing config for /chat: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - runtime issues
        logger.exception("Unhandled /chat error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return ChatResponse(response=text, trace_id=trace_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await run_turn_http(request.message)


def _require_callback_token(header_token: str | None, query_token: str | None) -> None:
    if not _callback_secret:
        raise HTTPException(status_code=500, detail="Approval callback secret not configured.")
    token = header_token or query_token
    if not token or not hmac.compare_digest(token, _callback_secret):
        raise HTTPException(status_code=401, detail="Invalid approval callback token.")


def _emit_feedback_telemetry(record: dict[str, Any]) -> None:
    connection_string = os.getenv("APPINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return
    trace_id = str(record.get("trace_id") or "").strip() or new_trace_id()
    run_id = str(record.get("run_id") or "").strip() or new_run_id()
    turn_id = new_turn_id()
    recorder = TraceRecorder(run_id=run_id, trace_id=trace_id, turn_id=turn_id)
    payload = {
        "feedback_id": record.get("id"),
        "scenario": record.get("scenario"),
        "decision": record.get("decision"),
        "reason": record.get("reason"),
        "rating": record.get("rating"),
        "source": record.get("source"),
    }
    recorder.record("feedback.submitted", payload)
    recorder.set_elapsed_ms(0)
    service_name = os.getenv("APPINSIGHTS_SERVICE_NAME", "thain")
    AppInsightsTraceSink(connection_string, service_name).emit(recorder.to_dict())


def _coerce_iso_date(value: str | None, default: datetime) -> str:
    if not value:
        return default.isoformat()
    raw = value.strip()
    if not raw:
        return default.isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{raw}T00:00:00+00:00")
        except ValueError:
            return default.isoformat()
    return parsed.astimezone(timezone.utc).isoformat()


def _feedback_response(record: dict[str, Any]) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(record.get("id") or ""),
        createdAtUtc=str(record.get("created_at_utc") or ""),
        traceId=record.get("trace_id"),
        runId=record.get("run_id"),
        scenario=str(record.get("scenario") or "answer"),
        decision=str(record.get("decision") or ""),
        reason=record.get("reason"),
        rating=record.get("rating"),
        comment=record.get("comment"),
        metadata=record.get("metadata"),
        source=record.get("source"),
    )


async def _apply_approval_decision(
    *,
    approval_id: str,
    decision: str,
    decided_by: str | None,
    decision_source: str,
    decided_at: str | None = None,
    tool_name: str | None = None,
    tool_args_hash: str | None = None,
    trace_id: str | None = None,
) -> dict[str, str]:
    if not _approval_store:
        raise HTTPException(status_code=500, detail="Approval store not configured.")

    record = await _approval_store.get(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Approval record not found.")
    if tool_name and str(record.get("tool_name")) != tool_name:
        raise HTTPException(status_code=400, detail="Tool name mismatch.")
    if tool_args_hash and str(record.get("tool_args_hash")) != tool_args_hash:
        raise HTTPException(status_code=400, detail="Tool payload hash mismatch.")
    record_trace_id = record.get("trace_id")
    if record_trace_id and trace_id and str(record_trace_id) != trace_id:
        raise HTTPException(status_code=400, detail="Trace ID mismatch.")

    decision = decision.strip().lower()
    if decision not in {"approved", "denied"}:
        raise HTTPException(status_code=400, detail="Invalid decision value.")

    updated = await _approval_store.record_decision(
        approval_id,
        decision=decision,
        decided_by=decided_by,
        decision_source=decision_source,
        decided_at=decided_at,
    )
    status = str(updated.get("status")) if updated else "unknown"
    return {"status": status}


@app.post("/approvals/callback", response_model=dict)
async def approvals_callback(
    payload: ApprovalCallbackRequest,
    x_thain_approval_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, str]:
    _require_callback_token(x_thain_approval_token, token)
    return await _apply_approval_decision(
        approval_id=payload.approval_id,
        decision=payload.decision,
        decided_by=payload.decided_by,
        decision_source=payload.decision_source or "logicapp-email",
        decided_at=payload.decided_at,
        tool_name=payload.tool_name,
        tool_args_hash=payload.tool_args_hash,
        trace_id=payload.trace_id,
    )


@app.get("/approvals/callback", response_model=dict)
async def approvals_callback_get(
    approval_id: str = Query(...),
    decision: str = Query(...),
    token: str | None = Query(default=None),
    decided_by: str | None = Query(default=None),
) -> dict[str, str]:
    _require_callback_token(None, token)
    return await _apply_approval_decision(
        approval_id=approval_id,
        decision=decision,
        decided_by=decided_by,
        decision_source="logicapp-email",
    )


@app.get("/approvals/{approval_id}", response_model=ApprovalStatusResponse)
async def get_approval_status(approval_id: str) -> ApprovalStatusResponse:
    if not _approval_store:
        raise HTTPException(status_code=404, detail="Approval store not configured.")
    record = await _approval_store.get(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Approval record not found.")
    return ApprovalStatusResponse(
        approval_id=approval_id,
        status=str(record.get("status") or "unknown"),
        approved=record.get("approved"),
        decision=record.get("decision"),
        decided_at=record.get("decided_at"),
        execution_status=record.get("execution_status"),
    )


@app.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackCreate) -> FeedbackResponse:
    if not _feedback_store:
        raise HTTPException(status_code=404, detail="Feedback store not configured.")

    feedback_id = request.id or f"FDB-{uuid.uuid4().hex[:12].upper()}"
    scenario = (request.scenario or "answer").strip().lower() or "answer"
    decision = request.decision.strip().lower()
    created_at_utc = request.created_at_utc or datetime.now(timezone.utc).isoformat()

    record = {
        "id": feedback_id,
        "created_at_utc": created_at_utc,
        "trace_id": request.trace_id,
        "run_id": request.run_id,
        "scenario": scenario,
        "decision": decision,
        "reason": request.reason,
        "rating": request.rating,
        "comment": request.comment,
        "metadata": request.metadata,
        "source": request.source,
    }

    stored = await _feedback_store.create(record)
    _emit_feedback_telemetry(stored)
    return _feedback_response(stored)


@app.get("/feedback/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(feedback_id: str) -> FeedbackResponse:
    if not _feedback_store:
        raise HTTPException(status_code=404, detail="Feedback store not configured.")
    record = await _feedback_store.get(feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback record not found.")
    return _feedback_response(record)


@app.get("/feedback/summary", response_model=FeedbackSummary)
async def feedback_summary(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> FeedbackSummary:
    if not _feedback_store:
        raise HTTPException(status_code=404, detail="Feedback store not configured.")

    now = datetime.now(timezone.utc)
    start_iso = _coerce_iso_date(from_, now - timedelta(days=30))
    end_iso = _coerce_iso_date(to, now)

    items = await _feedback_store.list_range(start_iso, end_iso)
    by_day: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_scenario: dict[str, int] = {}

    for item in items:
        created_at = str(item.get("created_at_utc") or "")
        day_key = created_at[:10] if len(created_at) >= 10 else "unknown"
        by_day[day_key] = by_day.get(day_key, 0) + 1

        decision = str(item.get("decision") or "unknown")
        by_decision[decision] = by_decision.get(decision, 0) + 1

        reason = str(item.get("reason") or "").strip()
        if reason:
            by_reason[reason] = by_reason.get(reason, 0) + 1

        scenario = str(item.get("scenario") or "answer")
        by_scenario[scenario] = by_scenario.get(scenario, 0) + 1

    override_count = by_decision.get("rejected", 0) + by_decision.get("overridden", 0)
    total = len(items)
    override_rate = (override_count / total) if total else None

    daily_counts = [
        {"date": day, "count": count} for day, count in sorted(by_day.items(), reverse=False)
    ]

    return FeedbackSummary(
        **{
            "from": start_iso,
            "to": end_iso,
            "total": total,
            "by_day": daily_counts,
            "by_decision": by_decision,
            "by_reason": by_reason,
            "by_scenario": by_scenario,
            "override_rate": override_rate,
        }
    )

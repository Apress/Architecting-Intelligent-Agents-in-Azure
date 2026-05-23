from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    response: str
    trace_id: str | None = None


class ApprovalCallbackRequest(BaseModel):
    approval_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    tool_args_hash: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    trace_id: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    decision_source: str | None = None


class ApprovalStatusResponse(BaseModel):
    approval_id: str
    status: str
    approved: bool | None = None
    decision: str | None = None
    decided_at: str | None = None
    execution_status: str | None = None

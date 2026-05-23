from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


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


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    created_at_utc: str | None = Field(default=None, alias="createdAtUtc")
    trace_id: str | None = Field(default=None, alias="traceId")
    run_id: str | None = Field(default=None, alias="runId")
    scenario: str = Field(default="answer")
    decision: str
    reason: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = None
    metadata: dict[str, Any] | None = None
    source: str | None = None


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    created_at_utc: str = Field(alias="createdAtUtc")
    trace_id: str | None = Field(default=None, alias="traceId")
    run_id: str | None = Field(default=None, alias="runId")
    scenario: str
    decision: str
    reason: str | None = None
    rating: int | None = None
    comment: str | None = None
    metadata: dict[str, Any] | None = None
    source: str | None = None


class FeedbackDailyCount(BaseModel):
    date: str
    count: int


class FeedbackSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    total: int
    by_day: list[FeedbackDailyCount]
    by_decision: dict[str, int]
    by_reason: dict[str, int]
    by_scenario: dict[str, int]
    override_rate: float | None = None

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ComplaintRecordModel(BaseModel):
    """Pydantic model describing a stored complaint record."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    customer_id: str = Field(alias="customerId")
    issue_category: str = Field(alias="issueCategory")
    summary: str
    raw_message: str = Field(alias="rawMessage")
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAt")
    source: str = "thain"
    embedding_id: Optional[str] = Field(default=None, alias="embeddingId")
    ttl_seconds: Optional[int] = Field(default=None, alias="ttl")
    ticket_created: bool = Field(default=False, alias="ticketCreated")
    notified_team: Optional[str] = Field(default=None, alias="notifiedTeam")
    outcome: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
        "json_encoders": {datetime: lambda dt: dt.isoformat()},
    }

    @classmethod
    def from_agent_payload(
        cls,
        *,
        customer_id: str,
        category: str,
        summary: str,
        message: str,
        confidence: float = 1.0,
        ttl_seconds: Optional[int] = None,
        ticket_created: bool = False,
        notified_team: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> "ComplaintRecordModel":
        return cls(
            customerId=customer_id,
            issueCategory=category,
            summary=summary,
            rawMessage=message,
            confidence=confidence,
            ttl=ttl_seconds,
            ticketCreated=ticket_created,
            notifiedTeam=notified_team,
            outcome=outcome,
        )


class ComplaintQuery(BaseModel):
    """Query parameters for retrieving previously stored complaints."""

    customer_id: str = Field(alias="customerId")
    category: Optional[str] = Field(default=None, alias="category")
    limit: int = 5

    model_config = {"populate_by_name": True}

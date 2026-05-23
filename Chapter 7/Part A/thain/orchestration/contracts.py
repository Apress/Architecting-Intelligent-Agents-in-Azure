from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List

STAGE_SAFETY = "safety_gate"
STAGE_TRIAGE = "triage"
STAGE_RECALL = "recall"
STAGE_KNOWLEDGE = "knowledge"
STAGE_ACTION = "action"
STAGE_MERGE = "merge"


@dataclass(frozen=True)
class SafetyResult:
    risk_level: str
    flags: List[str]
    response_mode: str
    tool_permissions: Dict[str, str]
    redactions_required: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TriageResult:
    category: str
    urgency: str
    needs_retrieval: bool
    needs_docs: bool
    action_candidate: str
    missing_info: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecallResult:
    matches: List[Dict[str, Any]]
    recency: str
    retrieval_mode: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeResult:
    docs: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionResult:
    ticket: Dict[str, Any] | None
    notification: Dict[str, Any] | None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedResponse:
    response_mode: str
    category: str
    summary: str
    trace_id: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Blackboard:
    turn_id: str
    message: Dict[str, Any]
    safety: SafetyResult | None = None
    triage: TriageResult | None = None
    recall: RecallResult | None = None
    knowledge: KnowledgeResult | None = None
    action: ActionResult | None = None
    failures: List[Dict[str, Any]] = field(default_factory=list)

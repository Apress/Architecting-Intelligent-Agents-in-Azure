from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from governance.safety import detect_safety_flags, unique_flags
from orchestration.contracts import Blackboard, FailureRecord


def record_failure(
    board: Blackboard,
    stage: str,
    error_type: str,
    message: str,
    severity: str = "error",
    recoverable: bool = True,
) -> None:
    board.failures.append(
        FailureRecord(
            stage=stage,
            error_type=error_type,
            message=message,
            severity=severity,
            recoverable=recoverable,
        )
    )


def blackboard_to_dict(board: Blackboard) -> Dict[str, Any]:
    data = asdict(board)
    return data


def build_message_metadata(message: str) -> Dict[str, Any]:
    flags = unique_flags(detect_safety_flags(message))
    return {
        "message_len": len(message.strip()),
        "has_urls": bool("http://" in message or "https://" in message),
        "safety_flags": flags,
    }


def build_stage_timeline(board: Blackboard) -> Dict[str, Any]:
    def stage_status(name: str, present: bool, failed: bool) -> str:
        if failed:
            return "failed"
        if present:
            return "completed"
        return "skipped"

    failure_stages = {failure.stage for failure in board.failures}
    timeline = {
        "safety": stage_status("safety", board.safety is not None, "safety" in failure_stages),
        "triage": stage_status("triage", board.triage is not None, "triage" in failure_stages),
        "recall": stage_status("recall", board.recall is not None, "recall" in failure_stages),
        "knowledge": stage_status("knowledge", board.knowledge is not None, "knowledge" in failure_stages),
        "action": stage_status("action", board.action is not None, "action" in failure_stages),
    }
    return {
        "timeline": timeline,
        "failures": [failure.to_dict() for failure in board.failures],
    }

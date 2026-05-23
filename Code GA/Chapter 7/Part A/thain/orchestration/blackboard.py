from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from orchestration.contracts import Blackboard


def record_failure(board: Blackboard, stage: str, error_type: str, message: str) -> None:
    board.failures.append(
        {
            "stage": stage,
            "error_type": error_type,
            "message": message,
        }
    )


def blackboard_to_dict(board: Blackboard) -> Dict[str, Any]:
    data = asdict(board)
    return data


def build_message_metadata(message: str) -> Dict[str, Any]:
    return {
        "message_len": len(message.strip()),
        "has_urls": bool("http://" in message or "https://" in message),
    }

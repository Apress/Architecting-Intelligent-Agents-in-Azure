from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def requires_approval(tool_type: str, enabled: bool) -> bool:
    return enabled and tool_type == "write"


class ApprovalService:
    def __init__(
        self,
        enabled: bool,
        prompt: Callable[[str], str] | None = None,
        on_decision: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._enabled = enabled
        self._prompt = prompt
        self._on_decision = on_decision

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def request_approval(self, tool_name: str, payload: dict[str, Any]) -> bool:
        if not self._enabled:
            return True

        prompt_text = (
            f"Approve write action '{tool_name}'? (y/n): "
        )
        if self._prompt:
            response = self._prompt(prompt_text)
        else:
            response = input(prompt_text)
        approved = str(response).strip().lower() in {"y", "yes"}
        decision = {
            "approval_id": f"APR-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            "tool_name": tool_name,
            "approved": approved,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "approved" if approved else "denied",
        }
        if self._on_decision:
            self._on_decision(decision)

        if approved:
            print(f"Approval granted for write action: {tool_name}")
        else:
            print(f"Approval denied for write action: {tool_name}")
        return approved

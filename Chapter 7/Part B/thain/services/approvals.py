from __future__ import annotations

from typing import Any, Callable


def requires_approval(tool_type: str, enabled: bool) -> bool:
    return enabled and tool_type == "write"


class ApprovalService:
    def __init__(self, enabled: bool, prompt: Callable[[str], str] | None = None) -> None:
        self._enabled = enabled
        self._prompt = prompt

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
        if approved:
            print(f"Approval granted for write action: {tool_name}")
        else:
            print(f"Approval denied for write action: {tool_name}")
        return approved

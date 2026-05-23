from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AgentError:
    error_type: str
    message: str
    stage: str
    tool_name: Optional[str] = None


class ToolExecutionError(AgentError):
    pass


class PolicyDeniedError(AgentError):
    pass


class ApprovalDeniedError(AgentError):
    pass


class ExternalServiceError(AgentError):
    pass


class TimeoutError(AgentError):
    pass


def normalize_error(exc: Exception, stage: str, tool_name: Optional[str] = None) -> AgentError:
    error_name = type(exc).__name__
    message = str(exc) or error_name
    lowered = error_name.lower()

    if "timeout" in lowered:
        return TimeoutError(error_type=error_name, message=message, stage=stage, tool_name=tool_name)
    if error_name in {"SemanticSearchError", "HttpResponseError", "ServiceRequestError"}:
        return ExternalServiceError(error_type=error_name, message=message, stage=stage, tool_name=tool_name)
    if error_name in {"PolicyDeniedError"}:
        return PolicyDeniedError(error_type=error_name, message=message, stage=stage, tool_name=tool_name)
    if error_name in {"ApprovalDeniedError"}:
        return ApprovalDeniedError(error_type=error_name, message=message, stage=stage, tool_name=tool_name)

    return ToolExecutionError(error_type=error_name, message=message, stage=stage, tool_name=tool_name)


def normalize_error_info(
    error_info: dict[str, object],
    stage: str,
    tool_name: Optional[str] = None,
) -> AgentError:
    error_type = str(error_info.get("error_type") or "ToolError")
    reason = str(error_info.get("reason") or "Tool error")
    return ToolExecutionError(error_type=error_type, message=reason, stage=stage, tool_name=tool_name)

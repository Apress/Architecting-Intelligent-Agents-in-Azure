import argparse
import os
import asyncio
import json
import re
import hashlib
import time
import inspect
import functools
import logging
import sys
import random
import dataclasses
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from azure.core.exceptions import HttpResponseError

from agent_framework import (
    Agent,
    AgentResponse,
    ContextProvider,
    FunctionTool,
    Message,
    SessionContext,
)

from agent_framework_foundry import FoundryChatClient
from agent_framework.devui import serve as serve_devui  # DevUI server launcher

from config.credentials import get_azure_credential, get_key_vault_secret
from config.settings import (
    AzureAgentConfig,
    AzureAIDocsSearchConfig,
    AzureAISearchConfig,
    ApprovalStoreConfig,
    ApprovalWorkflowConfig,
    MissingConfigError,
    PersistentMemoryConfig,
    load_config,
    load_auth_mode,
    load_approval_store_config,
    load_approval_workflow_config,
    load_docs_search_config,
    load_persistent_config,
    load_search_config,
    load_action_tools_config,
    load_write_approvals_enabled,
    load_multi_agent_config,
    validate_cloud_config,
)
from memory.buffer import ComplaintRecord, ConversationMemory
from memory.persistence import PersistentMemoryService, PersistentStoreError
from memory.persistent_provider import PersistentContextProvider
from memory.docs_service import DocsRetrievalService
from memory.semantic_provider import SemanticContextProvider
from memory.semantic_service import SemanticRecallService, SemanticSearchError
from models.complaint import ComplaintRecordModel
from tools.classifier import classify_issue, classify_issue_tool
from tools.search import create_search_tool
from tools.action_tools import create_action_tools, execute_approved_action
from services.approvals import ApprovalService
from services.approval_store import CosmosApprovalStore
from orchestration.runner import OrchestratorRunner
from orchestration.blackboard import build_message_metadata, build_stage_timeline
from governance.policy import PolicyEngine, default_policy_rules
from governance.errors import normalize_error, normalize_error_info
from governance.tool_kinds import get_tool_kind
from governance.logging_policy import apply_log_policy
from governance.safety import redact_pii, redact_pii_payload
from observability.redaction import redact_payload
from observability.trace_ids import new_run_id, new_trace_id, new_turn_id
from observability.tracing import TraceRecorder
from observability.trace_sinks import FileTraceSink, AppInsightsTraceSink


AUTH_MODE = load_auth_mode()
if AUTH_MODE == "managed_identity":
    validate_cloud_config()

ASYNC_AZURE_CREDENTIAL = get_azure_credential(AUTH_MODE, async_credential=True)
SYNC_AZURE_CREDENTIAL = get_azure_credential(AUTH_MODE, async_credential=False)

persistent_memory_config: PersistentMemoryConfig | None = load_persistent_config()
persistent_memory_service: PersistentMemoryService | None = (
    PersistentMemoryService(persistent_memory_config, credential=ASYNC_AZURE_CREDENTIAL)
    if persistent_memory_config
    else None
)
action_tools_config = load_action_tools_config()

semantic_search_config: AzureAISearchConfig | None = load_search_config()
docs_search_config: AzureAIDocsSearchConfig | None = load_docs_search_config()
approval_store_config: ApprovalStoreConfig | None = load_approval_store_config()
approval_workflow_config: ApprovalWorkflowConfig | None = load_approval_workflow_config()


def _resolve_managed_embedding_key() -> str:
    key_vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
    secret_name = os.getenv("KV_EMBEDDING_API_KEY_NAME", "").strip()
    embedding_key = get_key_vault_secret(
        vault_uri=key_vault_uri,
        credential=SYNC_AZURE_CREDENTIAL,
        name=secret_name,
    )
    if not embedding_key:
        raise MissingConfigError(
            "Missing embedding API key in managed identity mode. "
            "Set KEY_VAULT_URI and KV_EMBEDDING_API_KEY_NAME, or disable embedding-based retrieval."
        )
    return embedding_key


def _resolve_kv_secret_value(secret_name: str, label: str) -> str:
    key_vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
    if not key_vault_uri:
        raise MissingConfigError(f"Missing KEY_VAULT_URI required for {label}.")
    value = get_key_vault_secret(
        vault_uri=key_vault_uri,
        credential=SYNC_AZURE_CREDENTIAL,
        name=secret_name,
    )
    if not value:
        raise MissingConfigError(f"Missing Key Vault secret for {label}: {secret_name}.")
    return value


managed_embedding_key: str | None = None
if AUTH_MODE == "managed_identity":
    if semantic_search_config and not semantic_search_config.embedding_api_key:
        managed_embedding_key = managed_embedding_key or _resolve_managed_embedding_key()
        semantic_search_config = dataclasses.replace(
            semantic_search_config,
            embedding_api_key=managed_embedding_key,
        )
    if action_tools_config.enable_docs and docs_search_config and not docs_search_config.embedding_api_key:
        managed_embedding_key = managed_embedding_key or _resolve_managed_embedding_key()
        docs_search_config = dataclasses.replace(
            docs_search_config,
            embedding_api_key=managed_embedding_key,
        )
    if approval_workflow_config:
        if (
            not approval_workflow_config.logic_app_url
            and approval_workflow_config.logic_app_url_secret_name
        ):
            resolved_url = _resolve_kv_secret_value(
                approval_workflow_config.logic_app_url_secret_name,
                "approval workflow URL",
            )
            approval_workflow_config = dataclasses.replace(
                approval_workflow_config,
                logic_app_url=resolved_url,
            )
        if (
            not approval_workflow_config.callback_secret
            and approval_workflow_config.callback_secret_name
        ):
            resolved_secret = _resolve_kv_secret_value(
                approval_workflow_config.callback_secret_name,
                "approval callback secret",
            )
            approval_workflow_config = dataclasses.replace(
                approval_workflow_config,
                callback_secret=resolved_secret,
            )

semantic_service: SemanticRecallService | None = (
    SemanticRecallService(semantic_search_config, search_credential=ASYNC_AZURE_CREDENTIAL)
    if semantic_search_config
    else None
)
docs_service: DocsRetrievalService | None = (
    DocsRetrievalService(docs_search_config, search_credential=ASYNC_AZURE_CREDENTIAL)
    if action_tools_config.enable_docs and docs_search_config
    else None
)
multi_agent_config = load_multi_agent_config()
write_approvals_enabled = load_write_approvals_enabled()
approval_store: CosmosApprovalStore | None = None
if write_approvals_enabled:
    if not approval_store_config or not approval_workflow_config:
        raise MissingConfigError(
            "Write approvals are enabled but approval store/workflow configuration is missing."
        )
    if not approval_workflow_config.logic_app_url:
        raise MissingConfigError("Approval workflow URL is missing.")
    if not approval_workflow_config.callback_secret:
        raise MissingConfigError("Approval callback secret is missing.")
    approval_store = CosmosApprovalStore(approval_store_config, credential=ASYNC_AZURE_CREDENTIAL)
approval_service = ApprovalService(
    enabled=write_approvals_enabled,
    store=approval_store,
    workflow=approval_workflow_config,
)
policy_engine = PolicyEngine(default_policy_rules(write_approvals_enabled))
memory_store = ConversationMemory(capacity=5)
logger = logging.getLogger(__name__)
logging.getLogger("memory.persistent_provider").setLevel(logging.INFO)
logging.getLogger("memory.semantic_provider").setLevel(logging.INFO)
RUN_ID = new_run_id()
MODEL_PROFILE = (os.getenv("THAIN_MODEL_PROFILE", "standard").strip().lower() or "standard")
_RESPONSE_CACHE: dict[str, dict[str, Any]] = {}

BASE_INSTRUCTIONS = (
    "You are Thain, an enterprise customer support triage assistant. "
    "Always call the `classify_issue` tool to validate the category you return. "
    "If the tool's confidence is low, silently choose the best category yourself; do not mention the confidence or the fallback step. "
    "When you are given a list of recent complaints, explicitly consider how the new problem relates to them "
    "and mention any meaningful connections or contrasts in the Insight section. If additional historical context would improve the response, call the `search_similar_complaints` tool to retrieve similar complaints. "
    "Produce ONE triage summary card in Markdown using this template (do NOT emit JSON):\n"
    "**Triage Summary for Complaint ID #C-<YYYYMMDD><RAND4>**\n"
    "---\n"
    "**Issue Type**\n"
    "<Category Path>\n"
    "---\n"
    "**Summary**\n"
    "<One-sentence summary on the next line (no timestamps required).>\n"
    "---\n"
    "**Insight**\n"
    "<Reference prior complaints/context. If none apply, state 'No prior insight available.'>\n"
    "---\n"
    "**Suggest**\n"
    "<Concrete next action or investigation step>\n"
)

_APPROVAL_ID_PATTERN = re.compile(r"\bAPR-\d{13}-\d{3}\b", re.IGNORECASE)


def _extract_approval_id(message: str) -> str | None:
    match = _APPROVAL_ID_PATTERN.search(message)
    if not match:
        return None
    return match.group(0).upper()


async def _resolve_approval_record(
    approval_id: str,
    approval_store: CosmosApprovalStore | None,
) -> dict[str, Any] | None:
    if not approval_store:
        return None

    record = await approval_store.get(approval_id)
    if not record:
        return None

    status = str(record.get("status") or "pending").lower()
    if status != "pending":
        return record

    expires_at_raw = record.get("expires_at")
    if not expires_at_raw:
        return record

    try:
        expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
    except ValueError:
        return record

    if datetime.now(timezone.utc) <= expires_at:
        return record

    updated = await approval_store.record_decision(
        approval_id,
        decision="expired",
        decided_by="system",
        decision_source="system",
        decided_at=datetime.now(timezone.utc).isoformat(),
    )
    return updated or record


async def _handle_approval_status_request(
    approval_id: str,
    approval_store: CosmosApprovalStore | None,
    approval_service: ApprovalService,
    recorder: TraceRecorder,
    redactor: Callable[[Any], Any] | None = None,
) -> str:
    if not approval_store:
        return "Approval tracking is not configured. Please submit the request again."

    record = await _resolve_approval_record(approval_id, approval_store)
    if not record:
        return f"Approval ID {approval_id} was not found. Please verify the ID and try again."

    status = str(record.get("status") or "pending").lower()
    execution_status = str(record.get("execution_status") or "").lower()
    _record_event(
        recorder,
        "approval.status_check",
        {
            "approval_id": approval_id,
            "status": status,
            "execution_status": execution_status,
        },
        redactor=redactor,
    )
    if status in {"approved", "denied", "expired", "executed"}:
        _record_event(
            recorder,
            "approval.decision",
            {
                "approval_id": approval_id,
                "status": status,
                "decision": record.get("decision") or status,
                "decided_by": record.get("decided_by"),
                "decided_at": record.get("decided_at"),
                "decision_source": record.get("decision_source"),
                "tool_name": record.get("tool_name"),
            },
            redactor=redactor,
        )

    if status in {"denied", "expired"}:
        return f"Approval {approval_id} was {status}. The requested action was not performed."

    if status == "pending":
        return (
            f"Approval {approval_id} is still pending. "
            "Please check back after the approver responds."
        )

    if execution_status == "executed" or status == "executed":
        return f"Approval {approval_id} has already been executed."

    if status != "approved":
        return f"Approval {approval_id} is in status '{status}'."

    tool_name = str(record.get("tool_name") or "")
    tool_args = record.get("tool_args") or {}
    if not tool_name or not isinstance(tool_args, dict):
        return (
            f"Approval {approval_id} is approved, but the stored request payload is missing. "
            "Please re-submit the action request."
        )

    if not await approval_service.try_mark_executed(approval_id):
        return f"Approval {approval_id} has already been executed."

    try:
        result = execute_approved_action(tool_name, tool_args, approval_id=approval_id)
    except Exception:
        return (
            f"Approval {approval_id} was approved, but the action could not be executed. "
            "Please try again."
        )

    _record_event(
        recorder,
        "tool.result",
        {
            "tool_name": tool_name,
            "status": "ok",
            "duration_ms": 0,
            "result": redactor(result) if redactor else redact_payload(result),
        },
        redactor=redactor,
    )
    _record_event(
        recorder,
        "approval.execute",
        {
            "approval_id": approval_id,
            "tool_name": tool_name,
            "status": result.get("status"),
        },
        redactor=redactor,
    )

    if tool_name == "create_ticket":
        ticket_id = result.get("ticket_id") or "unknown"
        return f"Approval {approval_id} approved. Ticket created (ID: {ticket_id})."
    if tool_name == "notify_team":
        message_id = result.get("message_id") or "unknown"
        channel = result.get("channel") or "team"
        return f"Approval {approval_id} approved. Notification sent to {channel} (ID: {message_id})."
    return f"Approval {approval_id} approved. Action executed."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Thain support triage agent")
    parser.add_argument(
        "-m",
        "--message",
        help="Customer complaint to triage. If omitted, the script reads from stdin.",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run Thain in interactive REPL mode to preserve short-term memory during the session.",
    )
    # DevUI CLI options
    parser.add_argument(
        "--devui",
        action="store_true",
        help="Launch the Agent Framework DevUI to explore and interact with Thain.",
    )
    parser.add_argument(
        "--devui-host",
        default="127.0.0.1",
        help="Host interface for the DevUI server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--devui-port",
        type=int,
        default=8080,
        help="Port for the DevUI server (default: 8080).",
    )
    parser.add_argument(
        "--devui-open",
        action="store_true",
        help="Automatically open the DevUI in the browser when the server starts.",
    )
    parser.add_argument(
        "--devui-tracing",
        action="store_true",
        help="Enable OpenTelemetry tracing when launching the DevUI.",
    )
    return parser.parse_args()


def read_customer_message(args: argparse.Namespace) -> str:
    if args.message:
        return args.message.strip()

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped

    raise SystemExit("No customer message supplied. Use --message or pipe text into stdin.")

class MemoryContextProvider(ContextProvider):
    """Context provider that surfaces recent complaints to the agent."""

    def __init__(self, memory: ConversationMemory) -> None:
        super().__init__(source_id="memory")
        self._memory = memory

    async def before_run(self, *, agent: Any, session: Any, context: SessionContext, state: Any) -> None:
        instructions = self._memory.contextual_instructions()
        if instructions:
            context.instructions.append(instructions)




def _tool_name(tool: Any) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", "tool")


def _record_event(
    recorder: TraceRecorder,
    event_type: str,
    payload: Any,
    redactor: Callable[[Any], Any] | None = None,
) -> None:
    safe_payload = redactor(payload) if redactor else redact_payload(payload)
    safe_payload = apply_log_policy(event_type, safe_payload)
    recorder.record(event_type, safe_payload)

def _coerce_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        return max(int(raw), minimum)
    except ValueError:
        return max(default, minimum)


def _extract_usage(response: Any) -> dict[str, int] | None:
    usage = None
    for attr in ("usage", "token_usage", "tokens"):
        if hasattr(response, attr):
            usage = getattr(response, attr)
            if usage:
                break
    if usage is None:
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            usage = metadata.get("usage") or metadata.get("token_usage") or metadata.get("tokens")
    if usage is None and hasattr(response, "raw"):
        raw = getattr(response, "raw", None)
        if isinstance(raw, dict):
            usage = raw.get("usage") or raw.get("token_usage")

    usage_map = _coerce_mapping(usage)
    if not usage_map:
        return None

    prompt_tokens = (
        _coerce_int(usage_map.get("prompt_tokens"))
        or _coerce_int(usage_map.get("input_tokens"))
    )
    completion_tokens = (
        _coerce_int(usage_map.get("completion_tokens"))
        or _coerce_int(usage_map.get("output_tokens"))
    )
    total_tokens = _coerce_int(usage_map.get("total_tokens"))
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    return {
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "total_tokens": total_tokens or ((prompt_tokens or 0) + (completion_tokens or 0)),
    }


def _estimate_usage_heuristic(prompt_text: str, completion_text: str) -> dict[str, int]:
    # Conservative heuristic for token visibility when SDK usage is unavailable.
    prompt_tokens = max(1, int(len(prompt_text or "") / 4))
    completion_tokens = max(1, int(len(completion_text or "") / 4))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _resolve_usage(response: Any, prompt_text: str, completion_text: str) -> tuple[dict[str, int], str]:
    usage = _extract_usage(response)
    if usage:
        return usage, "sdk"
    return _estimate_usage_heuristic(prompt_text, completion_text), "heuristic"


def _extract_model_name(response: Any, config: AzureAgentConfig) -> str:
    metadata = getattr(response, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("model", "model_name", "deployment", "deployment_name"):
            value = metadata.get(key)
            if value:
                return str(value)
    for attr in ("model", "model_name", "deployment", "deployment_name"):
        if hasattr(response, attr):
            value = getattr(response, attr)
            if value:
                return str(value)
    return config.model


def _estimate_cost(usage: dict[str, int]) -> float | None:
    input_rate = (
        _parse_float_env("THAIN_COST_INPUT_PER_1K_USD")
        or _parse_float_env("THAIN_COST_INPUT_PER_1K")
    )
    output_rate = (
        _parse_float_env("THAIN_COST_OUTPUT_PER_1K_USD")
        or _parse_float_env("THAIN_COST_OUTPUT_PER_1K")
    )
    if input_rate is None and output_rate is None:
        return None
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = 0.0
    if input_rate is not None:
        cost += (prompt_tokens / 1000.0) * input_rate
    if output_rate is not None:
        cost += (completion_tokens / 1000.0) * output_rate
    return round(cost, 6)


def _compact_instruction_text(instructions: str) -> str:
    # Keep behavior the same while trimming avoidable whitespace and duplicates.
    compacted = re.sub(r"[ \t]{2,}", " ", instructions)
    compacted = re.sub(r"\n{3,}", "\n\n", compacted)
    lines: list[str] = []
    seen: set[str] = set()
    for line in compacted.splitlines():
        normalized = line.rstrip()
        dedupe_key = normalized.strip()
        if dedupe_key and len(dedupe_key) > 40:
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
        lines.append(normalized)
    return "\n".join(lines).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    value = text.strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _compact_response_sections(text: str) -> str:
    if not _parse_bool_env("THAIN_ENABLE_RESPONSE_COMPACTION", True):
        return text

    summary_limit = _parse_int_env("THAIN_RESPONSE_SUMMARY_MAX_CHARS", 300, minimum=80)
    suggest_limit = _parse_int_env("THAIN_RESPONSE_SUGGEST_MAX_CHARS", 520, minimum=160)

    compacted = text

    summary_marker = "**Summary**"
    insight_marker = "**Insight**"
    if summary_marker in compacted and insight_marker in compacted:
        start = compacted.find(summary_marker) + len(summary_marker)
        end = compacted.find(insight_marker, start)
        if end > start:
            summary_body = compacted[start:end].strip()
            summary_body = _truncate_text(summary_body, summary_limit)
            compacted = f"{compacted[:start]}\n{summary_body}\n{compacted[end:]}"

    suggest_marker = "**Suggest**"
    if suggest_marker in compacted:
        start = compacted.find(suggest_marker) + len(suggest_marker)
        suggest_body = compacted[start:].strip()
        if suggest_body:
            preserved_prefix = ""
            remaining_body = suggest_body
            if suggest_body.lower().startswith("action outcome:") and "\n" in suggest_body:
                first_line, rest = suggest_body.split("\n", 1)
                preserved_prefix = first_line.strip()
                remaining_body = rest.strip()
            remaining_budget = suggest_limit
            if preserved_prefix:
                remaining_budget = max(120, suggest_limit - len(preserved_prefix) - 1)
            truncated_body = _truncate_text(remaining_body, remaining_budget) if remaining_body else ""
            rebuilt_parts = [part for part in (preserved_prefix, truncated_body) if part]
            rebuilt = "\n".join(rebuilt_parts)
            compacted = f"{compacted[:start]}\n{rebuilt}\n"

    return compacted


def _cache_enabled() -> bool:
    return _parse_bool_env("THAIN_ENABLE_CACHE", False)


def _cache_ttl_seconds() -> int:
    return _parse_int_env("THAIN_CACHE_TTL_SECONDS", 120, minimum=10)


def _cache_max_entries() -> int:
    return _parse_int_env("THAIN_CACHE_MAX_ENTRIES", 200, minimum=20)


def _cache_eligible_message(message: str) -> bool:
    if _extract_approval_id(message):
        return False
    lower = message.strip().lower()
    blocked_markers = (
        "create ticket",
        "open ticket",
        "notify team",
        "send notification",
        "status apr-",
        "approve",
        "deny",
    )
    return not any(marker in lower for marker in blocked_markers)


def _cache_eligible_response(board: Any, text: str) -> bool:
    if getattr(board, "safety", None) and getattr(board.safety, "response_mode", "normal") != "normal":
        return False
    if getattr(board, "action", None):
        actions = getattr(board.action, "actions", []) or []
        if actions:
            # Block any response that involved side effects or approval state transitions.
            blocked_statuses = {"executed", "pending", "denied", "failed"}
            normalized_statuses = {str(action.get("status", "")).strip().lower() for action in actions}
            if normalized_statuses & blocked_statuses:
                return False
            # Allow cache only for pure no-op action paths (typically triage "none"/skipped).
            if any(status not in {"", "skipped"} for status in normalized_statuses):
                return False
            if any(
                str(action.get("action_type", "")).strip().lower() not in {"", "none"}
                for action in actions
            ):
                return False
            if any(
                str(action.get("reason", "")).strip().lower() not in {"", "no_candidate", "duplicate"}
                for action in actions
            ):
                return False
    lower = text.lower()
    blocked_markers = (
        "approval requested",
        "status apr-",
        "ticket created",
        "notification sent",
        "requested action was not performed",
    )
    return not any(marker in lower for marker in blocked_markers)


def _build_cache_key(customer_message: str, config: AzureAgentConfig, search_mode: str) -> str:
    normalized_message = customer_message.strip().lower()
    fingerprint = "|".join(
        [
            normalized_message,
            f"model={config.model}",
            f"profile={MODEL_PROFILE}",
            f"search={search_mode}",
            f"docs={action_tools_config.enable_docs}",
            f"tickets={action_tools_config.enable_tickets}",
            f"notify={action_tools_config.enable_notifications}",
            f"approvals={write_approvals_enabled}",
        ]
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _cache_get(cache_key: str) -> dict[str, Any] | None:
    entry = _RESPONSE_CACHE.get(cache_key)
    if not entry:
        return None
    now = time.time()
    if float(entry.get("expires_at", 0)) <= now:
        _RESPONSE_CACHE.pop(cache_key, None)
        return None
    return entry.get("value")


def _cache_put(cache_key: str, value: dict[str, Any]) -> None:
    now = time.time()
    ttl = _cache_ttl_seconds()
    _RESPONSE_CACHE[cache_key] = {
        "expires_at": now + ttl,
        "created_at": now,
        "value": value,
    }

    if len(_RESPONSE_CACHE) <= _cache_max_entries():
        return

    # Purge expired entries first, then evict oldest entries by insertion order.
    expired_keys = [key for key, item in _RESPONSE_CACHE.items() if float(item.get("expires_at", 0)) <= now]
    for key in expired_keys:
        _RESPONSE_CACHE.pop(key, None)
    while len(_RESPONSE_CACHE) > _cache_max_entries():
        oldest_key = next(iter(_RESPONSE_CACHE))
        _RESPONSE_CACHE.pop(oldest_key, None)


def _emit_trace(recorder: TraceRecorder) -> str:
    trace_output_dir = os.getenv("TRACE_OUTPUT_DIR", "traces")
    sink = FileTraceSink(trace_output_dir)
    trace_path = str(sink.build_path(recorder.to_dict()))
    appinsights_conn = os.getenv("APPINSIGHTS_CONNECTION_STRING")
    if appinsights_conn:
        service_name = os.getenv("APPINSIGHTS_SERVICE_NAME", "thain")
        app_sink = AppInsightsTraceSink(appinsights_conn, service_name)
        try:
            app_sink.emit(recorder.to_dict())
            _record_event(recorder, "trace.appinsights", {"status": "ok"})
        except Exception as exc:
            _record_event(
                recorder,
                "trace.appinsights",
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
            )
    _record_event(recorder, "trace.emitted", {"path": trace_path})
    return sink.emit(recorder.to_dict())


def _wrap_tool(
    tool: Any,
    recorder: TraceRecorder,
    policy_state: dict[str, Any] | None = None,
    redactor: Callable[[Any], Any] | None = None,
) -> Any:
    name = _tool_name(tool)
    if policy_state is None:
        policy_state = {}
    policy_state.setdefault("write_calls_in_turn", 0)
    policy_state.setdefault("retrieval_attempted", False)
    policy_state.setdefault("retrieval_results_count", None)
    policy_state.setdefault("policy_requires_approval", True)
    policy_state.setdefault("pii_write_block", True)
    policy_state.setdefault("warn_write_threshold", 2)

    if isinstance(tool, FunctionTool) and getattr(tool, "func", None) is not None:
        original = tool.func

        @functools.wraps(original)
        async def traced(*args: Any, **kwargs: Any) -> Any:
            tool_kind = get_tool_kind(name)
            if tool_kind in {"write", "ticket", "notify"}:
                policy_state["write_calls_in_turn"] += 1
            policy_decision = policy_engine.evaluate(tool_kind, policy_state)
            _record_event(
                recorder,
                "policy.check",
                {
                    "tool_name": name,
                    "tool_kind": tool_kind,
                    "decision": policy_decision.decision,
                    "matched_rule_ids": policy_decision.matched_rule_ids,
                    "enforced_rule_id": policy_decision.enforced_rule_id,
                    "reason": policy_decision.reason,
                },
                redactor=redactor,
            )
            if policy_decision.decision == "deny":
                _record_event(
                    recorder,
                    "tool.result",
                    {
                        "tool_name": name,
                        "status": "blocked",
                        "duration_ms": 0,
                        "error_type": "PolicyDenied",
                    },
                    redactor=redactor,
                )
                if tool_kind in {"write", "ticket", "notify"}:
                    return {"status": "denied", "approved": False, "reason": "policy_denied"}
                return []

            redacted_args = redact_payload(kwargs)
            if isinstance(redacted_args, dict):
                if "customer_message" in redacted_args:
                    redacted_args["customer_message_len"] = len(str(kwargs.get("customer_message", "")).strip())
                    redacted_args["customer_message"] = "<redacted>"
                if "summary" in redacted_args:
                    redacted_args["summary_len"] = len(str(kwargs.get("summary", "")).strip())
                    redacted_args["summary"] = "<redacted>"
            _record_event(
                recorder,
                "tool.call",
                {"tool_name": name, "args": redacted_args},
                redactor=redactor,
            )
            start = time.perf_counter()
            try:
                result = original(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                duration_ms = max(1, int((time.perf_counter() - start) * 1000))
                error = normalize_error(exc, stage="tool", tool_name=name)
                _record_event(
                    recorder,
                    "tool.result",
                    {
                        "tool_name": name,
                        "status": "error",
                        "duration_ms": duration_ms,
                        "error_type": error.error_type,
                    },
                    redactor=redactor,
                )
                raise
            duration_ms = max(1, int((time.perf_counter() - start) * 1000))
            if (
                isinstance(result, list)
                and result
                and isinstance(result[0], dict)
                and result[0].get("_trace_error")
            ):
                error_info = result[0].get("_trace_error", {})
                if tool_kind in {"retrieve", "read"} and name in {"search_similar_complaints", "retrieve_docs"}:
                    policy_state["retrieval_attempted"] = True
                    policy_state["retrieval_results_count"] = 0
                error = normalize_error_info(error_info, stage="tool", tool_name=name)
                _record_event(
                    recorder,
                    "tool.result",
                    {
                        "tool_name": name,
                        "status": "error",
                        "duration_ms": duration_ms,
                        "error_type": error.error_type,
                    },
                    redactor=redactor,
                )
                return []
            if tool_kind in {"retrieve", "read"} and name in {"search_similar_complaints", "retrieve_docs"}:
                policy_state["retrieval_attempted"] = True
                policy_state["retrieval_results_count"] = len(result) if isinstance(result, list) else 0
            _record_event(
                recorder,
                "tool.result",
                {
                    "tool_name": name,
                    "status": "ok",
                    "duration_ms": duration_ms,
                    "result": redact_payload(result),
                },
                redactor=redactor,
            )
            return result

        tool.func = traced
        return tool

    return tool


def parse_structured_response(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        segments = cleaned.split("```")
        if len(segments) >= 2:
            cleaned = segments[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
    candidates = [cleaned]
    if "{" in cleaned and "}" in cleaned:
        first = cleaned.find("{")
        last = cleaned.rfind("}") + 1
        if last > first:
            candidates.append(cleaned[first:last])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Agent response was not valid JSON: {cleaned}")


def _build_triage_card(customer_message: str, board: Any) -> str:
    def _truncate(text: str, limit: int = 220) -> str:
        cleaned = text.strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand = random.randint(1000, 9999)
    complaint_id = f"#C-{today}{rand}"

    issue_type = "General Inquiry"
    if board and getattr(board, "triage", None) and getattr(board.triage, "category", None):
        issue_type = str(board.triage.category)
    else:
        issue_type = str(classify_issue(customer_message).get("category", "General Inquiry"))

    summary = customer_message.strip()
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."

    insight = "No prior insight available."
    if board and getattr(board, "recall", None) and getattr(board.recall, "matches", None):
        matches = board.recall.matches or []
        if matches:
            first = matches[0]
            match_summary = first.get("summary") or first.get("rawMessage") or "a similar complaint"
            insight = f"Similar complaint found: {match_summary}"

    suggest = "Investigate the issue and validate configuration or hardware at the affected sites."
    if board and getattr(board, "knowledge", None) and getattr(board.knowledge, "docs", None):
        docs = board.knowledge.docs or []
        if docs:
            title = docs[0].get("title", "relevant troubleshooting documentation")
            content = docs[0].get("content") or docs[0].get("snippet") or ""
            content = _truncate(str(content))
            if content:
                suggest = f"Review '{title}'. Key guidance: {content}"
            else:
                suggest = f"Review '{title}' for relevant troubleshooting steps and apply the guidance."

    return (
        f"**Triage Summary for Complaint ID {complaint_id}**\n"
        "---\n"
        "**Issue Type**\n"
        f"{issue_type}\n"
        "---\n"
        "**Summary**\n"
        f"{summary}\n"
        "---\n"
        "**Insight**\n"
        f"{insight}\n"
        "---\n"
        "**Suggest**\n"
        f"{suggest}\n"
    )


def _ensure_triage_card(text: str, customer_message: str, board: Any) -> str:
    if getattr(board, "safety", None) and getattr(board.safety, "response_mode", "normal") != "normal":
        return text
    if "**Triage Summary for Complaint ID" in text:
        return text
    return _build_triage_card(customer_message, board)


def _extract_kb_guidance(board: Any, limit: int = 220) -> str | None:
    if not board or not getattr(board, "knowledge", None) or not getattr(board.knowledge, "docs", None):
        return None
    docs = board.knowledge.docs or []
    if not docs:
        return None
    for doc in docs:
        content = str(doc.get("content") or "").strip()
        if content:
            if len(content) > limit:
                content = content[: limit - 3].rstrip() + "..."
            return content
        snippet = str(doc.get("snippet") or "").strip()
        if snippet:
            if len(snippet) > limit:
                snippet = snippet[: limit - 3].rstrip() + "..."
            return snippet
    return None


def _enforce_kb_guidance(text: str, board: Any) -> str:
    guidance = _extract_kb_guidance(board)
    if not guidance:
        return text
    if "**Suggest**" not in text:
        return text

    parts = text.split("**Suggest**", 1)
    if len(parts) != 2:
        return text

    before = parts[0] + "**Suggest**"
    after = parts[1].lstrip()

    if guidance.lower() in after.lower() or "key guidance:" in after.lower():
        return text

    updated = f"{after.rstrip()} Key guidance: {guidance}"
    return f"{before}\n{updated}\n"


def _enforce_action_outcome(text: str, board: Any) -> str:
    if not board or not getattr(board, "action", None):
        return text
    if getattr(board, "safety", None) and getattr(board.safety, "response_mode", "normal") != "normal":
        return text

    actions = getattr(board.action, "actions", []) or []
    if not actions:
        return text

    ticket = getattr(board.action, "ticket", None) or {}
    notification = getattr(board.action, "notification", None) or {}

    outcome_parts: list[str] = []
    if any(action.get("action_type") == "ticket" and action.get("status") == "executed" for action in actions):
        ticket_id = ticket.get("ticket_id") or "unknown"
        outcome_parts.append(f"Ticket created (ID: {ticket_id}).")
    if any(action.get("action_type") == "notify" and action.get("status") == "executed" for action in actions):
        message_id = notification.get("message_id") or "unknown"
        channel = notification.get("channel") or "team"
        outcome_parts.append(f"Notification sent to {channel} (ID: {message_id}).")
    pending_actions = [action for action in actions if action.get("status") == "pending"]
    if pending_actions:
        approval_id = pending_actions[0].get("approval_id")
        if approval_id:
            outcome_parts.append(
                f"Approval requested (ID: {approval_id}). Ask 'status {approval_id}' to continue."
            )
        else:
            outcome_parts.append("Approval requested and pending.")
    if any(action.get("status") == "denied" for action in actions):
        outcome_parts.append("Requested action was not performed (approval denied).")
    if any(action.get("status") == "failed" for action in actions):
        outcome_parts.append("Requested action could not be completed due to a tool error.")

    if not outcome_parts:
        return text

    action_line = "Action outcome: " + " ".join(outcome_parts)

    # If actions executed but response implies denial, override with a deterministic confirmation.
    executed = any(action.get("status") == "executed" for action in actions)
    denial_markers = ("not granted", "not occur", "could not", "unable", "approval", "denied")
    if executed and any(marker in text.lower() for marker in denial_markers):
        return (
            "The requested actions were completed successfully. "
            f"{action_line}\n"
            "If you need additional escalation steps, let me know."
        )

    marker = "**Suggest**"
    if marker in text:
        parts = text.split(marker, 1)
        before = parts[0] + marker
        after = parts[1]
        if action_line in after:
            return text
        # Insert action line at the top of Suggest section and remove confirmation language.
        cleaned_after = after
        if executed:
            for phrase in (
                "confirm whether",
                "confirm that",
                "verify whether",
                "verify that",
                "approval was required",
                "approval is required",
            ):
                cleaned_after = cleaned_after.replace(phrase, "follow up to ensure")
        return f"{before}\n{action_line}\n{cleaned_after.lstrip()}"

    return text.rstrip() + "\n\n" + action_line + "\n"

def _build_safety_response(response_mode: str) -> str:
    templates = _load_safety_templates()
    if response_mode == "human_escalate":
        return templates["human_escalate"]
    return templates["refuse"]


_SAFETY_TEMPLATE_CACHE: dict[str, str] | None = None


def _load_safety_templates() -> dict[str, str]:
    global _SAFETY_TEMPLATE_CACHE
    if _SAFETY_TEMPLATE_CACHE is not None:
        return _SAFETY_TEMPLATE_CACHE

    defaults = {
        "human_escalate": (
            "I'm really sorry you're feeling this way. You’re not alone, and help is available.\n\n"
            "If you feel like you might hurt yourself or are in immediate danger, please call your local emergency number. "
            "In the U.S., you can call or text 988 to reach the Suicide & Crisis Lifeline (24/7). "
            "If you're outside the U.S., I can help find local support resources.\n\n"
            "If it helps, consider reaching out to someone you trust right now. I’m here to support you."
        ),
        "refuse": "I'm sorry, but I can't assist with that request.",
    }

    human_escalate = os.getenv("SAFETY_TEMPLATE_HUMAN_ESCALATE", "").strip()
    refuse = os.getenv("SAFETY_TEMPLATE_REFUSE", "").strip()

    key_vault_uri = os.getenv("KEY_VAULT_URI", "").strip()
    kv_human_name = os.getenv("KV_SAFETY_TEMPLATE_HUMAN_ESCALATE_NAME", "").strip()
    kv_refuse_name = os.getenv("KV_SAFETY_TEMPLATE_REFUSE_NAME", "").strip()

    if not human_escalate and AUTH_MODE == "managed_identity" and key_vault_uri and kv_human_name:
        human_escalate = (
            get_key_vault_secret(
                vault_uri=key_vault_uri,
                credential=SYNC_AZURE_CREDENTIAL,
                name=kv_human_name,
            )
            or ""
        )
    if not refuse and AUTH_MODE == "managed_identity" and key_vault_uri and kv_refuse_name:
        refuse = (
            get_key_vault_secret(
                vault_uri=key_vault_uri,
                credential=SYNC_AZURE_CREDENTIAL,
                name=kv_refuse_name,
            )
            or ""
        )

    _SAFETY_TEMPLATE_CACHE = {
        "human_escalate": human_escalate or defaults["human_escalate"],
        "refuse": refuse or defaults["refuse"],
    }
    return _SAFETY_TEMPLATE_CACHE

def update_memory(customer_message: str, payload: Dict[str, Any]) -> None:
    category = str(payload.get("category", "General Inquiry"))
    summary = str(payload.get("summary", customer_message[:120]))
    memory_store.add(ComplaintRecord(message=customer_message, category=category, summary=summary))

async def run_thain_agent(
    customer_message: str, config: AzureAgentConfig
) -> Tuple[Dict[str, Any], AgentResponse]:
    """Execute the Thain agent and return both structured payload and raw Agent Framework response."""

    trace_id = new_trace_id()
    turn_id = new_turn_id()
    recorder = TraceRecorder(run_id=RUN_ID, trace_id=trace_id, turn_id=turn_id)
    trace_emitted = False
    response_ready_recorded = False
    normalized: dict[str, Any] | None = None
    response: AgentResponse | None = None
    start_time = time.perf_counter()
    turn_metadata = build_message_metadata(customer_message)
    safety_flags = turn_metadata.get("safety_flags", [])
    pii_redaction_enabled = any(flag in {"contains_email", "contains_phone"} for flag in safety_flags)

    def trace_redactor(payload: Any) -> Any:
        if pii_redaction_enabled:
            payload = redact_pii_payload(payload)
        return redact_payload(payload)

    _record_event(
        recorder,
        "request.received",
        {
            "message_len": turn_metadata.get("message_len", len(customer_message.strip())),
            "has_urls": turn_metadata.get("has_urls", False),
            "safety_flags": safety_flags,
        },
        redactor=trace_redactor,
    )

    try:
        approval_id = _extract_approval_id(customer_message)
        if approval_id:
            status_text = await _handle_approval_status_request(
                approval_id,
                approval_store,
                approval_service,
                recorder,
                redactor=trace_redactor,
            )
            response = SimpleNamespace(
                text=status_text,
                messages=[Message(role="assistant", text=status_text)],
                metadata={},
            )
            normalized = {"category": "Approval Status", "summary": status_text}
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            recorder.set_elapsed_ms(elapsed_ms)
            _record_event(
                recorder,
                "response.ready",
                {
                    "category": normalized["category"],
                    "summary": "<redacted>",
                    "summary_len": len(status_text),
                    "elapsed_ms": elapsed_ms,
                },
                redactor=trace_redactor,
            )
            response_ready_recorded = True
            trace_path = _emit_trace(recorder)
            trace_emitted = True
            print(f"Trace written to {trace_path}")
            try:
                if not getattr(response, "metadata", None):
                    response.metadata = {}
                if isinstance(response.metadata, dict):
                    response.metadata["traceId"] = trace_id
            except Exception:
                pass
            return normalized, response

        search_mode = (semantic_search_config.mode if semantic_search_config else "off").strip().lower()
        cache_hit = False
        cache_key = ""
        cached_result: dict[str, Any] | None = None
        if _cache_enabled() and _cache_eligible_message(customer_message):
            cache_key = _build_cache_key(customer_message, config, search_mode)
            cached_result = _cache_get(cache_key)
            cache_hit = cached_result is not None

        if cache_hit and cached_result:
            cached_text = str(cached_result.get("response", "")).strip()
            cached_payload = cached_result.get("payload")
            response = SimpleNamespace(
                text=cached_text,
                messages=[Message(role="assistant", text=cached_text)],
                metadata={},
            )
            _record_event(
                recorder,
                "llm.usage",
                {
                    "model": config.model,
                    "model_profile": MODEL_PROFILE,
                    "usage_source": "cache",
                    "cache_hit": True,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_estimate_usd": 0.0,
                    "cost_estimate_available": True,
                },
                redactor=trace_redactor,
            )

            payload: dict[str, Any] | None
            if isinstance(cached_payload, dict):
                payload = dict(cached_payload)
            else:
                payload = None
                if cached_text:
                    try:
                        payload = parse_structured_response(cached_text)
                    except ValueError:
                        payload = None

            if payload is None:
                fallback = classify_issue(customer_message)
                payload = {
                    "category": fallback.get("category", "General Inquiry"),
                    "summary": customer_message,
                }

            if "category" not in payload:
                fallback = classify_issue(customer_message)
                payload["category"] = fallback["category"]
            if "summary" not in payload:
                payload["summary"] = customer_message
            if pii_redaction_enabled:
                payload["summary"] = redact_pii(str(payload.get("summary", "")))

            message_for_storage = redact_pii(customer_message) if pii_redaction_enabled else customer_message
            update_memory(message_for_storage, payload)
            normalized = {"category": payload["category"], "summary": payload["summary"]}
            if persistent_memory_service and persistent_memory_config:
                try:
                    await persistent_memory_service.persist(
                        customer_id=persistent_memory_config.customer_id,
                        category=normalized["category"],
                        summary=normalized["summary"],
                        message=message_for_storage,
                        confidence=float(payload.get("confidence", 1.0)),
                    )
                except PersistentStoreError:
                    logger.debug("Persistent memory write failed; continuing without durable storage.", exc_info=True)
            if semantic_service and semantic_search_config and search_mode != "off":
                try:
                    record = ComplaintRecordModel.from_agent_payload(
                        customer_id=semantic_search_config.customer_id,
                        category=normalized["category"],
                        summary=normalized["summary"],
                        message=message_for_storage,
                        confidence=float(payload.get("confidence", 1.0)),
                        ttl_seconds=(persistent_memory_config.ttl_seconds if persistent_memory_config else None),
                    )
                    await semantic_service.index_record(record)
                except (SemanticSearchError, Exception):
                    logger.debug("Semantic indexing failed; continuing without semantic storage.", exc_info=True)

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            recorder.set_elapsed_ms(elapsed_ms)
            _record_event(
                recorder,
                "response.ready",
                {
                    "category": normalized["category"],
                    "summary": "<redacted>",
                    "summary_len": len(str(normalized["summary"])),
                    "elapsed_ms": elapsed_ms,
                },
                redactor=trace_redactor,
            )
            response_ready_recorded = True
            trace_path = _emit_trace(recorder)
            trace_emitted = True
            print(f"Trace written to {trace_path}")
            try:
                if not getattr(response, "metadata", None):
                    response.metadata = {}
                if isinstance(response.metadata, dict):
                    response.metadata["traceId"] = trace_id
            except Exception:
                pass
            return normalized, response

        provider_chain: list[ContextProvider] = [MemoryContextProvider(memory_store)]
        if persistent_memory_service and persistent_memory_config:
            provider_chain.append(
                PersistentContextProvider(
                    memory_service=persistent_memory_service,
                    default_customer_id=persistent_memory_config.customer_id,
                )
            )

        policy_state = {
            "approvals_enabled": write_approvals_enabled,
            "search_mode": search_mode,
            "safety_flags": safety_flags,
        }
        if semantic_service and semantic_search_config and search_mode == "semantic":
            provider_chain.append(
                SemanticContextProvider(
                    service=semantic_service,
                    customer_id=semantic_search_config.customer_id,
                    lookup_limit=semantic_search_config.default_top_k,
                    mode=semantic_search_config.mode,
                )
            )
    
        search_tool = None
        if semantic_service and semantic_search_config:
            search_tool = create_search_tool(semantic_service, semantic_search_config)

        def _record_approval_request(request_payload: dict[str, Any]) -> None:
            _record_event(recorder, "approval.request", request_payload, redactor=trace_redactor)

        def _record_approval(decision: dict[str, Any]) -> None:
            _record_event(recorder, "approval.decision", decision, redactor=trace_redactor)

        run_approval_service = approval_service.with_context(
            trace_id=trace_id,
            run_id=RUN_ID,
            turn_id=turn_id,
            on_request=_record_approval_request,
            on_decision=_record_approval,
        )

        tools_list = [classify_issue_tool]
        if search_tool:
            tools_list.append(search_tool)

        action_tools = create_action_tools(
            action_tools_config,
            run_approval_service,
            docs_service=docs_service,
        )
        if action_tools:
            tools_list.extend(action_tools)

        wrapped_tools = [
            _wrap_tool(tool, recorder, policy_state, redactor=trace_redactor) for tool in tools_list
        ]
        wrapped_search_tool = next(
            (tool for tool in wrapped_tools if _tool_name(tool) == "search_similar_complaints"),
            None,
        )
        if search_mode != "agentic" and wrapped_search_tool in wrapped_tools:
            wrapped_tools.remove(wrapped_search_tool)

        tools_list = wrapped_tools
        tool_lookup = {_tool_name(tool): tool for tool in tools_list}
        docs_tool = tool_lookup.get("retrieve_docs")
        search_tool_for_recall = wrapped_search_tool if search_mode != "off" else None
        action_tools_for_orchestrator = {
            key: tool_lookup[key]
            for key in ("create_ticket", "notify_team")
            if key in tool_lookup
        }
    
        credential = ASYNC_AZURE_CREDENTIAL
        chat_client = FoundryChatClient(
            project_endpoint=config.endpoint,
            model=config.model,
            credential=credential,
        )
        customer_id = (
            persistent_memory_config.customer_id
            if persistent_memory_config
            else (semantic_search_config.customer_id if semantic_search_config else "thain-demo")
        )
        orchestrator = OrchestratorRunner(
            config=multi_agent_config,
            chat_client=chat_client,
            search_tool=search_tool_for_recall,
            docs_tool=docs_tool,
            action_tools=action_tools_for_orchestrator,
            search_mode=search_mode,
            default_top_k=(semantic_search_config.default_top_k if semantic_search_config else 3),
            customer_id=customer_id,
            approvals_enabled=write_approvals_enabled,
        )
        board = await orchestrator.run(customer_message, str(turn_id))
        if board.safety and "pii" in board.safety.redactions_required:
            pii_redaction_enabled = True
        context_block = orchestrator.context_block(board)
        timeline = build_stage_timeline(board)

        response_mode = board.safety.response_mode if board.safety else "normal"
        if response_mode != "normal":
            safety_text = _build_safety_response(response_mode)
            response = SimpleNamespace(
                text=safety_text,
                messages=[Message(role="assistant", text=safety_text)],
                metadata={},
            )
        else:
            instructions = BASE_INSTRUCTIONS
            if context_block:
                instructions += f"\n{context_block}"
            if timeline:
                instructions += (
                    "\nStage timeline:\n"
                    f"- safety: {timeline['timeline'].get('safety')}\n"
                    f"- triage: {timeline['timeline'].get('triage')}\n"
                    f"- recall: {timeline['timeline'].get('recall')}\n"
                    f"- knowledge: {timeline['timeline'].get('knowledge')}\n"
                    f"- action: {timeline['timeline'].get('action')}\n"
                )
            if board.knowledge and board.knowledge.docs:
                instructions += (
                    " Knowledge context is present with relevant document content. "
                    "Synthesize the document guidance into your response. "
                    "In the Suggest section, include at least one concrete step or policy detail from the retrieved documents. "
                    "If you cannot extract a concrete step, explicitly state that the KB content is too general. "
                    "Do not merely reference document titles."
                )
            if board.recall and board.recall.matches is not None:
                instructions += (
                    " Recall context is present. Do not claim that no similar complaints were found "
                    "if recall results are non-empty."
                )
            if board.action and board.action.actions:
                if any(action.get("status") == "executed" for action in board.action.actions):
                    instructions += (
                        " Actions were executed and approved. Confirm the actions occurred "
                        "(ticket created and/or team notified) and do not say approval is required."
                    )
                if any(action.get("status") == "denied" for action in board.action.actions):
                    instructions += (
                        " At least one action was denied. State that the action was not performed "
                        "and that approval was not granted."
                    )
                if any(action.get("status") == "pending" for action in board.action.actions):
                    instructions += (
                        " At least one action is pending approval. Provide the approval ID "
                        "and instruct the user to ask for status to continue."
                    )
            if search_mode != "agentic":
                instructions = instructions.replace(
                    "If additional historical context would improve the response, call the `search_similar_complaints` tool to retrieve similar complaints. ",
                    "",
                )
            else:
                instructions += (
                    " If the user asks whether to escalate, notify, or open a ticket, "
                    "and historical evidence would help justify the decision, and you have not already retrieved evidence in this turn, "
                    "call the `search_similar_complaints` tool before responding."
                )
                instructions += (
                    " If the user asks for known procedures, playbooks, or SOPs, "
                    "call the `retrieve_docs` tool before responding."
                )
                instructions += (
                    " If the user explicitly asks to notify a team or send a notification, "
                    "call the `notify_team` tool before responding."
                )
                instructions += (
                    " If the user mention about creating a ticket, "
                    "you must call the `create_ticket` tool before responding."
                )
                instructions += (
                    " If the user asks to both check similar incidents and create a ticket in the same request, "
                    "call `search_similar_complaints` first, then call `create_ticket` if appropriate."
                )
                instructions += (
                    " If a write tool returns status: denied or approved: false, explicitly state that the action did not occur and that approval was not granted for the request. "
                    "If a write tool returns status: pending, state that approval was requested and provide the approval_id. "
                    "Tell the user to ask `status <approval_id>` to continue once approved. "
                    "Do not say or imply that the action has been executed. "
                    "Do not recommend creating the ticket or sending a notification in the Suggest section when approval is pending or denied."
                )

            action_notes = []
            if action_tools_config.enable_tickets:
                action_notes.append("create_ticket (write)")
            if action_tools_config.enable_notifications:
                action_notes.append("notify_team (write)")
            if action_tools_config.enable_docs:
                action_notes.append("retrieve_docs (read)")
            if action_notes:
                instructions += " You may use the following tools when appropriate: " + ", ".join(action_notes) + "."
            instructions = _compact_instruction_text(instructions)

            chat_tools = tools_list
            tool_choice = {
                "mode": "required",
                "required_function_name": classify_issue_tool.name,
            }
            if (board.recall is not None) or (board.knowledge is not None) or (board.action is not None):
                # Orchestrator already gathered evidence / executed actions; prevent duplicate tool calls.
                chat_tools = []
                tool_choice = {"mode": "none"}

            agent = Agent(
                client=chat_client,
                name="Thain",
                instructions=instructions,
                tools=chat_tools,
                context_providers=provider_chain,
                default_options={"tool_choice": tool_choice},
            )

            response = await agent.run(customer_message)

        raw_text = response.text.strip()
        raw_text = _ensure_triage_card(raw_text, customer_message, board)
        raw_text = _enforce_action_outcome(raw_text, board)
        raw_text = _enforce_kb_guidance(raw_text, board)
        raw_text = _compact_response_sections(raw_text)
        usage, usage_source = _resolve_usage(response, customer_message, raw_text)
        model_name = _extract_model_name(response, config)
        cost_estimate = _estimate_cost(usage)
        cache_hit = False
        _record_event(
            recorder,
            "llm.usage",
            {
                "model": model_name,
                "model_profile": MODEL_PROFILE,
                "usage_source": usage_source,
                "cache_hit": cache_hit,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_estimate_usd": cost_estimate,
                "cost_estimate_available": cost_estimate is not None,
            },
            redactor=trace_redactor,
        )
        try:
            if response.messages:
                response.messages[-1] = Message(role="assistant", text=raw_text)
        except Exception:
            pass
        if not raw_text:
            raise RuntimeError("Agent run completed but produced no assistant message.")
    
        try:
            payload = parse_structured_response(raw_text)
        except ValueError:
            fallback = classify_issue(customer_message)
            payload = {
                "category": fallback.get("category", "General Inquiry"),
                "summary": customer_message,
            }
    
        if "category" not in payload:
            fallback = classify_issue(customer_message)
            payload["category"] = fallback["category"]
        if "summary" not in payload:
            payload["summary"] = customer_message
        if pii_redaction_enabled:
            payload["summary"] = redact_pii(str(payload.get("summary", "")))
    
        message_for_storage = redact_pii(customer_message) if pii_redaction_enabled else customer_message
        update_memory(message_for_storage, payload)
        normalized = {"category": payload["category"], "summary": payload["summary"]}
        if cache_key and _cache_enabled() and _cache_eligible_response(board, raw_text):
            _cache_put(
                cache_key,
                {
                    "response": raw_text,
                    "payload": normalized,
                },
            )
        if persistent_memory_service and persistent_memory_config:
            try:
                await persistent_memory_service.persist(
                    customer_id=persistent_memory_config.customer_id,
                    category=normalized["category"],
                    summary=normalized["summary"],
                    message=message_for_storage,
                    confidence=float(payload.get("confidence", 1.0)),
                )
            except PersistentStoreError:
                logger.debug("Persistent memory write failed; continuing without durable storage.", exc_info=True)
        if semantic_service and semantic_search_config and search_mode != "off":
            try:
                record = ComplaintRecordModel.from_agent_payload(
                    customer_id=semantic_search_config.customer_id,
                    category=normalized["category"],
                    summary=normalized["summary"],
                    message=message_for_storage,
                    confidence=float(payload.get("confidence", 1.0)),
                    ttl_seconds=(persistent_memory_config.ttl_seconds if persistent_memory_config else None),
                )
                await semantic_service.index_record(record)
            except (SemanticSearchError, Exception):
                logger.debug("Semantic indexing failed; continuing without semantic storage.", exc_info=True)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        recorder.set_elapsed_ms(elapsed_ms)
        _record_event(
            recorder,
            "response.ready",
            {
                "category": normalized["category"],
                "summary": "<redacted>",
                "summary_len": len(str(normalized["summary"])),
                "elapsed_ms": elapsed_ms,
            },
            redactor=trace_redactor,
        )
        response_ready_recorded = True
        trace_path = _emit_trace(recorder)
        trace_emitted = True
        print(f"Trace written to {trace_path}")
        try:
            if not getattr(response, "metadata", None):
                response.metadata = {}
            if isinstance(response.metadata, dict):
                response.metadata["traceId"] = trace_id
                response.metadata["stageTimeline"] = timeline
        except Exception:
            pass
    
        # AgentResponse.value is read-only in newer agent-framework versions.
        return normalized, response
    
    
    except Exception as exc:
        error = normalize_error(exc, stage="run")
        _record_event(
            recorder,
            "error.occurred",
            {
                "error_type": error.error_type,
                "message": error.message,
                "stage": error.stage,
                "tool_name": error.tool_name,
            },
            redactor=trace_redactor,
        )
        raise
    finally:
        if not trace_emitted:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            recorder.set_elapsed_ms(elapsed_ms)
            if normalized is not None and not response_ready_recorded:
                _record_event(
                    recorder,
                    "response.ready",
                    {
                        "category": normalized["category"],
                        "summary": "<redacted>",
                        "summary_len": len(str(normalized["summary"])),
                        "elapsed_ms": elapsed_ms,
                    },
                    redactor=trace_redactor,
                )
            trace_path = _emit_trace(recorder)
            print(f"Trace written to {trace_path}")

async def run_thain_async(customer_message: str, config: AzureAgentConfig) -> Dict[str, Any]:
    """Async triage routine built on the Microsoft Agent Framework."""

    payload, _ = await run_thain_agent(customer_message, config)
    return payload


def run_thain(customer_message: str, config: Optional[AzureAgentConfig] = None) -> Dict[str, Any]:
    """Synchronous facade used by CLI, REPL, and DevUI integrations."""

    resolved_config = config or load_config()
    return asyncio.run(run_thain_async(customer_message, resolved_config))


async def run_thain_text_async(
    customer_message: str, config: AzureAgentConfig
) -> tuple[str, str | None]:
    """Return the user-facing response text and trace_id for HTTP calls."""

    _, agent_response = await run_thain_agent(customer_message, config)
    trace_id = None
    try:
        metadata = getattr(agent_response, "metadata", None)
        if isinstance(metadata, dict):
            trace_id = metadata.get("traceId")
    except Exception:
        trace_id = None
    return agent_response.text, trace_id


def run_thain_text(customer_message: str, config: Optional[AzureAgentConfig] = None) -> tuple[str, str | None]:
    """Sync wrapper for HTTP layer."""

    resolved_config = config or load_config()
    return asyncio.run(run_thain_text_async(customer_message, resolved_config))


def _extract_latest_role_text(messages: Any, role: str) -> Optional[str]:
    """Helper to pull the latest message text for a given role from Agent Framework structures."""

    if messages is None:
        return None

    if isinstance(messages, Message):
        if messages.role == role:
            return messages.text
        return None

    if isinstance(messages, (list, tuple)):
        for item in reversed(messages):
            text = _extract_latest_role_text(item, role)
            if text:
                return text
        return None

    if isinstance(messages, str):
        return messages if role == "user" else None

    return None




# --- DevUI helper classes/functions ---
class ThainDevAgent:
    """Thin wrapper that adapts run_thain for the Agent Framework DevUI."""

    def __init__(self, config: AzureAgentConfig) -> None:
        self._config = config
        self.id = "thain"
        self.entity_id = "thain"
        self.name = "Thain"
        self.description = "Customer support triage assistant that classifies complaints and generates summaries."
        self.instructions = BASE_INSTRUCTIONS
        search_mode = (semantic_search_config.mode if semantic_search_config else "off").strip().lower()
        tools: list[Any] = [classify_issue_tool]
        if semantic_service and semantic_search_config and search_mode == "agentic":
            tools.append(create_search_tool(semantic_service, semantic_search_config))
        tools.extend(
            create_action_tools(
                action_tools_config,
                approval_service,
                docs_service=docs_service,
            )
        )
        self.tools = tools

    async def run(self, messages: Any, **kwargs: Any) -> AgentResponse:
        user_text = _extract_latest_role_text(messages, "user")
        if not user_text:
            raise ValueError("ThainDevAgent requires a user message to operate.")

        _, agent_response = await run_thain_agent(user_text, self._config)
        try:
            if not getattr(agent_response, "metadata", None):
                agent_response.metadata = {}
            if isinstance(agent_response.metadata, dict):
                agent_response.metadata["entityId"] = self.id
        except Exception:
            pass
        return agent_response


def launch_devui(host: str, port: int, auto_open: bool, tracing_enabled: bool) -> None:
    """Launch the Agent Framework DevUI with the Thain agent registered."""

    config = load_config()
    agent_entity = ThainDevAgent(config)

    # DevUI b260123 expects metadata.entity_id; allow legacy keys from the UI.
    try:
        from agent_framework_devui.models._openai_custom import AgentFrameworkRequest
        from agent_framework_devui._executor import AgentFrameworkExecutor

        def _patched_get_entity_id(self: Any) -> str | None:
            metadata = getattr(self, "metadata", None) or {}
            if isinstance(metadata, dict):
                entity_id = (
                    metadata.get("entity_id")
                    or metadata.get("entityId")
                    or metadata.get("agent_id")
                )
                if entity_id:
                    return entity_id
            extra_body = getattr(self, "extra_body", None)
            if isinstance(extra_body, dict):
                entity_id = extra_body.get("entity_id")
                if entity_id:
                    return entity_id
            model = getattr(self, "model", None)
            if isinstance(model, str) and model.strip():
                return model
            return None

        AgentFrameworkRequest.get_entity_id = _patched_get_entity_id  # type: ignore[assignment]

        # NOTE: Do not patch execute_streaming here; it is an async generator in DevUI.
    except Exception:
        pass
    serve_kwargs: dict[str, Any] = {
        "entities": [agent_entity],
        "host": host,
        "port": port,
        "auto_open": auto_open,
    }

    try:
        params = inspect.signature(serve_devui).parameters
    except (TypeError, ValueError):
        params = {}

    if "tracing_enabled" in params:
        serve_kwargs["tracing_enabled"] = tracing_enabled
    elif "instrumentation_enabled" in params:
        serve_kwargs["instrumentation_enabled"] = tracing_enabled
    if "auth_enabled" in params:
        serve_kwargs["auth_enabled"] = False

    serve_devui(**serve_kwargs)

# --- End DevUI helper classes/functions ---


def main() -> None:
    args = parse_args()
    if args.devui and args.interactive:
        sys.exit("Choose either --devui or --interactive, not both.")
    if args.devui and args.message:
        sys.exit("The --devui option cannot be combined with --message.")

    if args.devui:
        try:
            launch_devui(args.devui_host, args.devui_port, args.devui_open, args.devui_tracing)
        except MissingConfigError as config_error:
            sys.exit(f"Configuration error: {config_error}")
        except Exception as unexpected:
            sys.exit(f"Failed to launch DevUI: {unexpected}")
        return

    if args.interactive:
        print("Entering interactive Thain session. Type 'exit' or 'quit' to leave.\n")
        while True:
            try:
                user_input = input("Customer message> ").strip()
            except KeyboardInterrupt:
                print("\nExiting.")
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            try:
                response_text, _ = run_thain_text(user_input)
            except MissingConfigError as config_error:
                print(f"Configuration error: {config_error}")
                break
            except HttpResponseError as azure_error:
                print(f"Azure request failed: {azure_error}")
                break
            except Exception as unexpected:
                print(f"Unexpected failure: {unexpected}")
                break

            print(response_text)
        return

    customer_message = read_customer_message(args)

    try:
        response_text, _ = run_thain_text(customer_message)
    except MissingConfigError as config_error:
        sys.exit(f"Configuration error: {config_error}")
    except HttpResponseError as azure_error:
        sys.exit(f"Azure request failed: {azure_error}")
    except Exception as unexpected:
        sys.exit(f"Unexpected failure: {unexpected}")

    print(response_text)


if __name__ == "__main__":
    main()































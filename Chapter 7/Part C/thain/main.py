import argparse
import os
import asyncio
import json
import re
import time
import inspect
import functools
import logging
import sys
from contextlib import AsyncExitStack
from typing import Any, Callable, Dict, Optional, Tuple

from azure.core.exceptions import HttpResponseError
from azure.identity.aio import DefaultAzureCredential

from agent_framework import (
    AgentRunResponse,
    AggregateContextProvider,
    ChatAgent,
    ChatMessage,
    Context,
    ContextProvider,
    ToolMode,
    AIFunction,
)
from agent_framework.azure import AzureAIAgentClient
from agent_framework.devui import serve as serve_devui  # DevUI server launcher

from config.settings import (
    AzureAgentConfig,
    AzureAISearchConfig,
    MissingConfigError,
    PersistentMemoryConfig,
    load_config,
    load_persistent_config,
    load_search_config,
    load_action_tools_config,
    load_write_approvals_enabled,
    load_multi_agent_config,
)
from memory.buffer import ComplaintRecord, ConversationMemory
from memory.persistence import PersistentMemoryService, PersistentStoreError
from memory.persistent_provider import PersistentContextProvider
from memory.semantic_provider import SemanticContextProvider
from memory.semantic_service import SemanticRecallService, SemanticSearchError
from models.complaint import ComplaintRecordModel
from tools.classifier import classify_issue, classify_issue_tool
from tools.search import create_search_tool
from tools.action_tools import create_action_tools
from services.approvals import ApprovalService
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
from observability.trace_sinks import FileTraceSink


persistent_memory_config: PersistentMemoryConfig | None = load_persistent_config()
persistent_memory_service: PersistentMemoryService | None = (
    PersistentMemoryService(persistent_memory_config) if persistent_memory_config else None
)
semantic_search_config: AzureAISearchConfig | None = load_search_config()
_search_mode = (semantic_search_config.mode if semantic_search_config else "off").strip().lower()
semantic_service: SemanticRecallService | None = (
    SemanticRecallService(semantic_search_config) if semantic_search_config and _search_mode != "off" else None
)
action_tools_config = load_action_tools_config()
multi_agent_config = load_multi_agent_config()
write_approvals_enabled = load_write_approvals_enabled()
approval_service = ApprovalService(enabled=write_approvals_enabled)
policy_engine = PolicyEngine(default_policy_rules(write_approvals_enabled))
memory_store = ConversationMemory(capacity=5)
logger = logging.getLogger(__name__)
logging.getLogger("memory.persistent_provider").setLevel(logging.INFO)
logging.getLogger("memory.semantic_provider").setLevel(logging.INFO)
RUN_ID = new_run_id()

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
        self._memory = memory

    async def invoking(self, messages: Any, **kwargs: Any) -> Context:  # type: ignore[override]
        instructions = self._memory.contextual_instructions()
        return Context(instructions=instructions) if instructions else Context()




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


def _emit_trace(recorder: TraceRecorder) -> str:
    trace_output_dir = os.getenv("TRACE_OUTPUT_DIR", "traces")
    sink = FileTraceSink(trace_output_dir)
    trace_path = str(sink.build_path(recorder.to_dict()))
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

    if isinstance(tool, AIFunction) and getattr(tool, "func", None) is not None:
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

def update_memory(customer_message: str, payload: Dict[str, Any]) -> None:
    category = str(payload.get("category", "General Inquiry"))
    summary = str(payload.get("summary", customer_message[:120]))
    memory_store.add(ComplaintRecord(message=customer_message, category=category, summary=summary))

async def run_thain_agent(
    customer_message: str, config: AzureAgentConfig
) -> Tuple[Dict[str, Any], AgentRunResponse]:
    """Execute the Thain agent and return both structured payload and raw Agent Framework response."""

    trace_id = new_trace_id()
    turn_id = new_turn_id()
    recorder = TraceRecorder(run_id=RUN_ID, trace_id=trace_id, turn_id=turn_id)
    trace_emitted = False
    response_ready_recorded = False
    normalized: dict[str, Any] | None = None
    response: AgentRunResponse | None = None
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
        provider_chain: list[ContextProvider] = [MemoryContextProvider(memory_store)]
        if persistent_memory_service and persistent_memory_config:
            provider_chain.append(
                PersistentContextProvider(
                    memory_service=persistent_memory_service,
                    default_customer_id=persistent_memory_config.customer_id,
                )
            )
    
        search_mode = (semantic_search_config.mode if semantic_search_config else "off").strip().lower()
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
    
        context_provider: ContextProvider | AggregateContextProvider
        if len(provider_chain) == 1:
            context_provider = provider_chain[0]
        else:
            context_provider = AggregateContextProvider(provider_chain)
    
        search_tool = None
        if semantic_service and semantic_search_config:
            search_tool = create_search_tool(semantic_service, semantic_search_config)

        def _record_approval(decision: dict[str, Any]) -> None:
            _record_event(recorder, "approval.decision", decision, redactor=trace_redactor)

        run_approval_service = ApprovalService(
            enabled=write_approvals_enabled,
            on_decision=_record_approval,
        )

        tools_list = [classify_issue_tool]
        if search_tool:
            tools_list.append(search_tool)

        action_tools = create_action_tools(action_tools_config, run_approval_service)
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
    
        async with AsyncExitStack() as stack:
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            stack.push_async_callback(credential.close)
    
            chat_client = AzureAIAgentClient(
                project_endpoint=config.endpoint,
                model_deployment_name=config.model,
                async_credential=credential,
            )
            await stack.enter_async_context(chat_client)
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
            if response_mode != "normal":
                instructions += (
                    " Safety response mode is active. Do not call any tools. "
                    "Provide a refusal or human escalation response as indicated by the response_mode."
                )
            if board.knowledge and board.knowledge.docs:
                instructions += (
                    " Knowledge context is present. Do not claim that no documents were found; "
                    "reference at least one retrieved document title in the Suggest section."
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
                    "Do not say or imply that the action is pending, being initiated, or partially completed. "
                    "Do not recommend creating the ticket or sending a notification in the Suggest section. "
                    "Explain that approval is required before the action can be performed, and ask whether the user would like to retry the request with approval, "
                    "notify the appropriate team, or choose an alternative action. "
                    "Do not use words such as 'proceed' or otherwise imply that the action was taken."
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
    
            chat_tools = tools_list
            tool_choice = ToolMode.REQUIRED(classify_issue_tool.name)
            if response_mode != "normal":
                chat_tools = []
                tool_choice = ToolMode.NONE
            elif (board.recall is not None) or (board.knowledge is not None) or (board.action is not None):
                # Orchestrator already gathered evidence / executed actions; prevent duplicate tool calls.
                chat_tools = []
                tool_choice = ToolMode.NONE

            agent = ChatAgent(
                chat_client=chat_client,
                name="Thain",
                instructions=instructions,
                tools=chat_tools,
                context_providers=context_provider,
                tool_choice=tool_choice,
                store=True,
            )
            await stack.enter_async_context(agent)
    
            response = await agent.run(customer_message)
    
        raw_text = response.text.strip()
        raw_text = _enforce_action_outcome(raw_text, board)
        try:
            if response.messages:
                response.messages[-1] = ChatMessage(role="assistant", text=raw_text)
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
    
        response.value = normalized
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


def _extract_latest_role_text(messages: Any, role: str) -> Optional[str]:
    """Helper to pull the latest message text for a given role from Agent Framework structures."""

    if messages is None:
        return None

    if isinstance(messages, ChatMessage):
        message_role = getattr(messages.role, "value", None)
        if message_role == role:
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
        tools.extend(create_action_tools(action_tools_config, approval_service))
        self.tools = tools

    async def run(self, messages: Any, **kwargs: Any) -> AgentRunResponse:
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
    serve_devui(entities=[agent_entity], host=host, port=port, auto_open=auto_open, tracing_enabled=tracing_enabled)

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
                response = run_thain(user_input)
            except MissingConfigError as config_error:
                print(f"Configuration error: {config_error}")
                break
            except HttpResponseError as azure_error:
                print(f"Azure request failed: {azure_error}")
                break
            except Exception as unexpected:
                print(f"Unexpected failure: {unexpected}")
                break

            print(json.dumps(response, ensure_ascii=False))
        return

    customer_message = read_customer_message(args)

    try:
        response = run_thain(customer_message)
    except MissingConfigError as config_error:
        sys.exit(f"Configuration error: {config_error}")
    except HttpResponseError as azure_error:
        sys.exit(f"Azure request failed: {azure_error}")
    except Exception as unexpected:
        sys.exit(f"Unexpected failure: {unexpected}")

    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()































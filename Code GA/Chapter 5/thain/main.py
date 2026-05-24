import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Dict, Optional, Tuple

from azure.core.exceptions import HttpResponseError
from azure.identity.aio import DefaultAzureCredential

from agent_framework import (
    Agent,
    AgentResponse,
    ContextProvider,
    Message,
    SessionContext,
)
from agent_framework_foundry import FoundryChatClient
from agent_framework.devui import serve as serve_devui

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
write_approvals_enabled = load_write_approvals_enabled()
approval_service = ApprovalService(enabled=write_approvals_enabled)
memory_store = ConversationMemory(capacity=5)
logger = logging.getLogger(__name__)
logging.getLogger("memory.persistent_provider").setLevel(logging.INFO)
logging.getLogger("memory.semantic_provider").setLevel(logging.INFO)

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

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: SessionContext,
        state: dict,
    ) -> None:
        instructions = self._memory.contextual_instructions()
        if instructions:
            context.instructions.append(instructions)


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


def update_memory(customer_message: str, payload: Dict[str, Any]) -> None:
    category = str(payload.get("category", "General Inquiry"))
    summary = str(payload.get("summary", customer_message[:120]))
    memory_store.add(ComplaintRecord(message=customer_message, category=category, summary=summary))


async def run_thain_agent(
    customer_message: str, config: AzureAgentConfig
) -> Tuple[Dict[str, Any], AgentResponse]:
    """Execute the Thain agent and return both structured payload and raw Agent Framework response."""

    provider_chain: list[ContextProvider] = [MemoryContextProvider(memory_store)]
    if persistent_memory_service and persistent_memory_config:
        provider_chain.append(
            PersistentContextProvider(
                memory_service=persistent_memory_service,
                default_customer_id=persistent_memory_config.customer_id,
            )
        )

    search_mode = (semantic_search_config.mode if semantic_search_config else "off").strip().lower()
    if semantic_service and semantic_search_config and search_mode == "semantic":
        provider_chain.append(
            SemanticContextProvider(
                service=semantic_service,
                customer_id=semantic_search_config.customer_id,
                lookup_limit=semantic_search_config.default_top_k,
                mode=semantic_search_config.mode,
            )
        )

    tools_list = [classify_issue_tool]
    if semantic_service and semantic_search_config and search_mode == "agentic":
        tools_list.append(create_search_tool(semantic_service, semantic_search_config))
    action_tools = create_action_tools(action_tools_config, approval_service)
    if action_tools:
        tools_list.extend(action_tools)

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    try:
        chat_client = FoundryChatClient(
            project_endpoint=config.endpoint,
            model=config.model,
            credential=credential,
        )

        instructions = BASE_INSTRUCTIONS
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

        agent = Agent(
            client=chat_client,
            name="Thain",
            instructions=instructions,
            tools=tools_list,
            context_providers=provider_chain,
            default_options={"tool_choice": {"mode": "required", "required_function_name": classify_issue_tool.name}},
        )

        response = await agent.run(customer_message)

        raw_text = response.text.strip()
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

        update_memory(customer_message, payload)
        normalized = {"category": payload["category"], "summary": payload["summary"]}
        if persistent_memory_service and persistent_memory_config:
            try:
                await persistent_memory_service.persist(
                    customer_id=persistent_memory_config.customer_id,
                    category=normalized["category"],
                    summary=normalized["summary"],
                    message=customer_message,
                    confidence=float(payload.get("confidence", 1.0)),
                )
            except PersistentStoreError:
                logger.debug("Persistent memory write failed; continuing without durable storage.", exc_info=True)
        if semantic_service and semantic_search_config:
            try:
                record = ComplaintRecordModel.from_agent_payload(
                    customer_id=semantic_search_config.customer_id,
                    category=normalized["category"],
                    summary=normalized["summary"],
                    message=customer_message,
                    confidence=float(payload.get("confidence", 1.0)),
                    ttl_seconds=(persistent_memory_config.ttl_seconds if persistent_memory_config else None),
                )
                await semantic_service.index_record(record)
            except (SemanticSearchError, Exception):
                logger.debug("Semantic indexing failed; continuing without semantic storage.", exc_info=True)
        return normalized, response
    finally:
        await credential.close()


async def run_thain_async(customer_message: str, config: AzureAgentConfig) -> Dict[str, Any]:
    """Async triage routine built on the Microsoft Agent Framework."""

    payload, _ = await run_thain_agent(customer_message, config)
    return payload


def run_thain(customer_message: str, config: Optional[AzureAgentConfig] = None) -> Dict[str, Any]:
    """Synchronous facade returning the structured payload (category + summary)."""

    resolved_config = config or load_config()
    return asyncio.run(run_thain_async(customer_message, resolved_config))


def run_thain_text(customer_message: str, config: Optional[AzureAgentConfig] = None) -> str:
    """Synchronous facade returning the agent's formatted response text for CLI display."""

    resolved_config = config or load_config()
    _, agent_response = asyncio.run(run_thain_agent(customer_message, resolved_config))
    return agent_response.text


def _extract_latest_role_text(messages: Any, role: str) -> Optional[str]:
    """Helper to pull the latest message text for a given role from Agent Framework structures."""

    if messages is None:
        return None
    if isinstance(messages, Message):
        if messages.role == role:  # role is now a plain string in GA
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


class _SingleResponseStream:
    """Adapter for DevUI streaming when the chapter uses the non-streaming runner."""

    def __init__(self, response_coro: Any, entity_id: str | None = None) -> None:
        self._response_coro = response_coro
        self._entity_id = entity_id
        self._response: AgentResponse | None = None
        self._yielded = False

    def __aiter__(self) -> "_SingleResponseStream":
        return self

    async def __anext__(self) -> AgentResponse:
        if self._yielded:
            raise StopAsyncIteration
        self._yielded = True
        return await self.get_final_response()

    async def get_final_response(self) -> AgentResponse:
        if self._response is None:
            _, response = await self._response_coro
            self._apply_entity_metadata(response)
            self._response = response
        return self._response

    def _apply_entity_metadata(self, response: AgentResponse) -> None:
        if not self._entity_id:
            return
        try:
            metadata = getattr(response, "metadata", None)
            if not isinstance(metadata, dict):
                metadata = {}
                response.metadata = metadata
            metadata.setdefault("entityId", self._entity_id)
            metadata.setdefault("entity_id", self._entity_id)
        except Exception:
            pass



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

    def run(self, messages: Any, *, stream: bool = False, session: Any = None, **kwargs: Any) -> Any:
        user_text = _extract_latest_role_text(messages, "user")
        if not user_text:
            raise ValueError("ThainDevAgent requires a user message to operate.")

        response_stream = _SingleResponseStream(
            run_thain_agent(user_text, self._config),
            entity_id=getattr(self, "id", None),
        )
        if stream:
            return response_stream
        return response_stream.get_final_response()

def launch_devui(host: str, port: int, auto_open: bool, tracing_enabled: bool) -> None:
    """Launch the Agent Framework DevUI with the Thain agent registered."""

    config = load_config()
    agent_entity = ThainDevAgent(config)
    serve_devui(entities=[agent_entity], host=host, port=port, auto_open=auto_open, instrumentation_enabled=tracing_enabled, auth_enabled=False)


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
                response = run_thain_text(user_input)
            except MissingConfigError as config_error:
                print(f"Configuration error: {config_error}")
                break
            except HttpResponseError as azure_error:
                print(f"Azure request failed: {azure_error}")
                break
            except Exception as unexpected:
                print(f"Unexpected failure: {unexpected}")
                break

            print(response)
        return

    customer_message = read_customer_message(args)

    try:
        response = run_thain_text(customer_message)
    except MissingConfigError as config_error:
        sys.exit(f"Configuration error: {config_error}")
    except HttpResponseError as azure_error:
        sys.exit(f"Azure request failed: {azure_error}")
    except Exception as unexpected:
        sys.exit(f"Unexpected failure: {unexpected}")

    print(response)


if __name__ == "__main__":
    main()

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
    MissingConfigError,
    PersistentMemoryConfig,
    load_config,
    load_persistent_config,
)
from memory.buffer import ComplaintRecord, ConversationMemory
from memory.persistence import PersistentMemoryService, PersistentStoreError
from memory.persistent_provider import PersistentContextProvider
from tools.classifier import classify_issue, classify_issue_tool


persistent_memory_config: PersistentMemoryConfig | None = load_persistent_config()
persistent_memory_service: PersistentMemoryService | None = (
    PersistentMemoryService(persistent_memory_config) if persistent_memory_config else None
)
memory_store = ConversationMemory(capacity=5)
logger = logging.getLogger(__name__)

BASE_INSTRUCTIONS = (
    "You are Thain, a concise customer support triage assistant. "
    "Listen to a single customer complaint, reason about the likely issue, and respond with a JSON "
    "object that includes `category` and `summary` keys. "
    "Call the `classify_issue` tool to validate the category you return. "
    "If the tool's confidence is low, silently choose the best category yourself; do not mention the confidence or the fallback step. "
    "Keep the summary brief (one sentence). "
    "When you are given a list of recent complaints, explicitly consider how the new problem relates to them "
    "and mention any meaningful connections or contrasts in your summary."
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

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    try:
        chat_client = FoundryChatClient(
            project_endpoint=config.endpoint,
            model=config.model,
            credential=credential,
        )

        agent = Agent(
            client=chat_client,
            name="Thain",
            instructions=BASE_INSTRUCTIONS,
            tools=[classify_issue_tool],
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
        return normalized, response
    finally:
        await credential.close()


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


class ThainDevAgent:
    """Thin wrapper that adapts run_thain for the Agent Framework DevUI."""

    def __init__(self, config: AzureAgentConfig) -> None:
        self._config = config
        self.name = "Thain"
        self.description = "Customer support triage assistant that classifies complaints and generates summaries."
        self.instructions = BASE_INSTRUCTIONS
        self.tools = [classify_issue_tool]

    async def run(self, messages: Any, **kwargs: Any) -> AgentResponse:
        user_text = _extract_latest_role_text(messages, "user")
        if not user_text:
            raise ValueError("ThainDevAgent requires a user message to operate.")

        _, agent_response = await run_thain_agent(user_text, self._config)
        return agent_response


def launch_devui(host: str, port: int, auto_open: bool, tracing_enabled: bool) -> None:
    """Launch the Agent Framework DevUI with the Thain agent registered."""

    config = load_config()
    agent_entity = ThainDevAgent(config)
    serve_devui(
        entities=[agent_entity],
        host=host,
        port=port,
        auto_open=auto_open,
        instrumentation_enabled=tracing_enabled,
        auth_enabled=False,
    )


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

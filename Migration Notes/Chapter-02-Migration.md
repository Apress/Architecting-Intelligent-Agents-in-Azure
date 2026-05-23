# Chapter 2 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework-azure-ai==1.0.0b251016` (Oct 2025)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 24/24 passed ✅

---

## Package Changes

### Before (beta)
```
agent-framework-azure-ai==1.0.0b251016
agent-framework-devui==1.0.0b251016
```

### After (GA)
```
agent-framework==1.5.0
agent-framework-foundry==1.5.0
agent-framework-devui==1.0.0b260519  # pinned tested beta — not intended for production
```

**Why:** The beta shipped as a single monolithic Azure-specific package. GA splits into a provider-neutral core (`agent-framework`) and a separate Azure Foundry integration (`agent-framework-foundry`). Note: `agent-framework-azure-ai==1.0.0rc6` is incompatible with 1.5.0 core — do not mix them.

---

## API Changes

### 1. `ChatAgent` → `Agent`

**Before:**
```python
from agent_framework import ChatAgent
agent = ChatAgent(
    chat_client=chat_client,
    name="Thain",
    instructions=BASE_INSTRUCTIONS,
    tools=[classify_issue_tool],
    context_providers=memory_provider,
    tool_choice=ToolMode.REQUIRED(classify_issue_tool.name),
    store=True,
)
async with agent:
    response = await agent.run(customer_message)
```

**After:**
```python
from agent_framework import Agent
agent = Agent(
    client=chat_client,
    name="Thain",
    instructions=BASE_INSTRUCTIONS,
    tools=[classify_issue_tool],
    context_providers=[memory_provider],
    default_options={"mode": "required", "required_function_name": classify_issue_tool.name},
)
response = await agent.run(customer_message)
```

Key differences:
- `chat_client=` → `client=`
- `tool_choice=ToolMode.REQUIRED(name)` → `default_options={"mode": "required", "required_function_name": name}`
- `store=True` removed — agent history is now managed via sessions (optional; stateless by default)
- `context_providers=single_provider` → `context_providers=[list]` (always a list)
- No `async with` needed — `Agent` is no longer an async context manager

---

### 2. `AzureAIAgentClient` → `FoundryChatClient`

**Before:**
```python
from agent_framework.azure import AzureAIAgentClient
chat_client = AzureAIAgentClient(
    project_endpoint=config.endpoint,
    model_deployment_name=config.model,
    async_credential=credential,
)
await stack.enter_async_context(chat_client)
```

**After:**
```python
from agent_framework_foundry import FoundryChatClient
chat_client = FoundryChatClient(
    project_endpoint=config.endpoint,
    model=config.model,
    credential=credential,
)
# No async context manager — instantiate directly
```

Key differences:
- Package: `agent_framework.azure` → `agent_framework_foundry`
- Class: `AzureAIAgentClient` → `FoundryChatClient`
- Param: `model_deployment_name=` → `model=`
- Param: `async_credential=` → `credential=` (accepts sync or async Azure credentials)
- No `AsyncExitStack` needed — `FoundryChatClient` is not an async context manager

---

### 3. `@ai_function` → `@tool`

**Before:**
```python
from agent_framework import ai_function

@ai_function(name="classify_issue", description="...")
def classify_issue_tool(customer_message: Annotated[str, "..."]) -> ...:
    ...
```

**After:**
```python
from agent_framework import tool

@tool(name="classify_issue", description="...")
def classify_issue_tool(customer_message: Annotated[str, "..."]) -> ...:
    ...
```

The `@tool` decorator returns a `FunctionTool` object (was `AIFunction`). The `.name` attribute still works the same way, so `classify_issue_tool.name` is still valid for `default_options`.

---

### 4. `ContextProvider` — Complete Interface Change

The most significant change. `ContextProvider` now uses a pipeline model instead of returning a `Context` object.

**Before:**
```python
from agent_framework import Context, ContextProvider

class MemoryContextProvider(ContextProvider):
    async def invoking(self, messages, **kwargs) -> Context:
        instructions = self._memory.contextual_instructions()
        return Context(instructions=instructions) if instructions else Context()
```

**After:**
```python
from agent_framework import ContextProvider, SessionContext

class MemoryContextProvider(ContextProvider):
    def __init__(self, memory: ConversationMemory) -> None:
        super().__init__(source_id="memory")   # source_id is now required
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
```

Key differences:
- `invoking()` → `before_run()` (keyword-only args, returns `None`)
- `Context` class is removed — instead mutate `context.instructions` directly
- `source_id` parameter required in `super().__init__(source_id="...")`
- New `after_run()` method available for post-response processing (optional)

---

### 5. `AggregateContextProvider` Removed

**Before:**
```python
from agent_framework import AggregateContextProvider
context_provider = AggregateContextProvider(provider_chain)
agent = ChatAgent(..., context_providers=context_provider)
```

**After:**
```python
# Just pass the list directly
agent = Agent(..., context_providers=provider_chain)
```

`Agent.context_providers` now accepts `Sequence[ContextProvider]` natively.

---

### 6. `AgentRunResponse` → `AgentResponse`

**Before:**
```python
from agent_framework import AgentRunResponse
async def run_thain_agent(...) -> Tuple[Dict, AgentRunResponse]:
```

**After:**
```python
from agent_framework import AgentResponse
async def run_thain_agent(...) -> Tuple[Dict, AgentResponse]:
```

`response.text` and `response.value` work identically.

---

### 7. `ChatMessage` → `Message`

**Before:**
```python
from agent_framework import ChatMessage
if isinstance(messages, ChatMessage):
    message_role = getattr(messages.role, "value", None)  # role was an enum
    if message_role == role:
        return messages.text
```

**After:**
```python
from agent_framework import Message
if isinstance(messages, Message):
    if messages.role == role:   # role is now a plain string
        return messages.text
```

`Message.text` is a property that concatenates all text `Content` objects in the message.

---

### 8. DevUI: `tracing_enabled` renamed to `instrumentation_enabled`

**Before:**
```python
serve_devui(entities=[...], host=host, port=port, auto_open=auto_open, tracing_enabled=tracing_enabled)
```

**After:**
```python
serve_devui(entities=[...], host=host, port=port, auto_open=auto_open, instrumentation_enabled=tracing_enabled)
```

**Note on DevUI validation:** DevUI is used in the book as a learning aid. It makes tool calls, traces, and agent reasoning more visible than the command line. The GA codebase does not include DevUI-specific tests. Validate examples using the command line (`python main.py --message "..."`) or the automated test suite (`pytest tests/`).

---

## New Tests Added

Chapter 2 originally had no test file. The GA version adds `tests/test_chapter2.py` with 24 unit tests covering:

- Keyword classifier (all 6 categories + unknown fallback)
- `FunctionTool` `.name` attribute
- `ConversationMemory` (capacity, eviction, instructions formatting)
- `MemoryContextProvider` (new `before_run` interface, `source_id`)
- `parse_structured_response` (plain JSON, fenced, embedded)
- `_extract_latest_role_text` (DevUI helper, all message types)

**Result: 24/24 passed ✅**

---

## Post-Migration Review Fixes (May 2026)

The following issues were caught in a post-migration review and fixed:

### 1. Credential Not Closed (Bug)
`run_thain_agent` created `DefaultAzureCredential` but never called `await credential.close()`. Fixed by wrapping the agent run in `try/finally`:
```python
credential = DefaultAzureCredential(...)
try:
    chat_client = FoundryChatClient(...)
    agent = Agent(...)
    response = await agent.run(customer_message)
finally:
    await credential.close()
```

### 2. Unused `ToolMode` Import
`from agent_framework import ... ToolMode` was left in imports but never used in the migrated code. Removed.

### 3. README.md Described Beta Stack
`README.md` still referenced `Assistants`, `azure-ai-agents`, `ChatAgent`, `AzureAIAgentClient`, and `@ai_function`. Updated to reflect GA APIs: `Agent`, `FoundryChatClient`, `@tool`, and `before_run`.

### 4. `FoundryChatClient` Parameter Name
`FoundryChatClient` uses `project_endpoint=` (same as `AzureAIAgentClient` beta), not `endpoint=`. The Ch2 code was already correct. Note: early Ch6/Ch7 migration drafts used `endpoint=` (incorrect) — that was also fixed in the same review pass.

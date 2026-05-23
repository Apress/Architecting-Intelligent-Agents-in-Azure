# Chapter 9 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework==1.0.0b260123` (Jan 2026)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 55/55 passed per version (v1.1 ✅ v1.11 ✅ v1.12 ✅)

---

## What Chapter 9 Introduces

Chapter 9 adds **feedback loops, LLM-as-judge evaluation, and policy hardening** across three sprints:

- `v1.1` — Feedback store, triage card pipeline, multi-agent orchestration (blackboard), approval workflow
- `v1.11` — LLM-as-judge evaluation harness (`infra/scripts/v11_eval_judge.py`)
- `v1.12` — Policy hardening: PII redaction, safety gate, stricter governance rules

Each version is an independent, testable snapshot of Thain at that sprint.

---

## Package Changes

| Before (beta) | After (GA) |
|---|---|
| `agent-framework==1.0.0b260123` | `agent-framework==1.5.0` |
| `agent-framework-core==1.0.0b260123` | `agent-framework-core==1.5.0` |
| `agent-framework-azure-ai==1.0.0b260123` | `agent-framework-foundry==1.5.0` (split package) |
| `agent-framework-devui==1.0.0b260123` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-ai-agents>=1.1.0` | removed |
| `agent-framework-a2a==1.0.0b260123` | removed (unused) |
| `agent-framework-copilotstudio==1.0.0b260123` | removed (unused) |
| `agent-framework-mem0==1.0.0b260123` | removed (unused) |
| `agent-framework-purview==1.0.0b260123` | removed (unused) |
| `agent-framework-redis==1.0.0b260123` | removed (unused) |
| `azure-ai-projects==2.0.0b3` | removed (unused) |

---

## API Changes

All changes from Chapters 2–8 apply here. Chapter 9 introduces several additional files compared to earlier chapters; all relevant files are migrated.

---

### 1. `@ai_function` → `@tool` in All Tool Files

**`tools/classifier.py`** — 1 decorator

**`tools/search.py`** — 1 decorator (inside factory function)

**`tools/action_tools.py`** — 3 decorators (one per action tool, inside factory)

**`tests/test_tracing.py`** and **`tests/test_policy_tracing.py`** — inline tool decorators used for tracing tests

```python
# Before
from agent_framework import ai_function

@ai_function(name="create_ticket", description="...")
async def create_ticket(...): ...
```

```python
# After
from agent_framework import tool

@tool(name="create_ticket", description="...")
async def create_ticket(...): ...
```

---

### 2. `ChatAgent` → `Agent` (in `agents/triage_agent.py` and `main.py`)

**`agents/triage_agent.py`:**

```python
# Before
from agent_framework import ChatAgent, ToolMode

agent = ChatAgent(
    chat_client=self._chat_client,
    name="TriageAgent",
    instructions=instructions,
    tools=[],
    default_options={
        "tool_choice": {"mode": "none"},
        "store": False,
    },
)
response = await agent.run(message)
raw = response.message.content if response.message else ""
```

```python
# After
from agent_framework import Agent

agent = Agent(
    client=self._chat_client,
    name="TriageAgent",
    instructions=instructions,
    tools=[],
    default_options={"mode": "none"},
)
response = await agent.run(message)
raw = response.text if response.text else ""
```

Changes: `chat_client=` → `client=`; removed `"store": False`; `tool_choice` dict flattened into `default_options`; `response.message.content` → `response.text`.

---

### 3. `AzureAIAgentClient` → `FoundryChatClient`

`main.py` in beta used `AzureAIAgentClient` with a complex parameter-inspection shim to handle credential variants:

```python
# Before
from agent_framework.azure import AzureAIAgentClient

chat_client_kwargs = {"project_endpoint": config.endpoint, "model_deployment_name": config.model}
client_params = inspect.signature(AzureAIAgentClient).parameters
if "credential" in client_params:
    chat_client_kwargs["credential"] = credential
elif "async_credential" in client_params:
    chat_client_kwargs["async_credential"] = credential
chat_client = AzureAIAgentClient(**chat_client_kwargs)
await stack.enter_async_context(chat_client)
```

```python
# After
from agent_framework_foundry import FoundryChatClient

chat_client = FoundryChatClient(
    project_endpoint=config.endpoint,
    model=config.model,
    credential=credential,
)
```

Note: `model_deployment_name=` → `model=`. The credential shim and parameter inspection are removed.

---

### 4. `AsyncExitStack` Removed

Ch9 beta used `async with AsyncExitStack() as stack:` to manage both the chat client and the agent as async context managers. In GA, neither requires this:

```python
# Before
from contextlib import AsyncExitStack

async with AsyncExitStack() as stack:
    chat_client = AzureAIAgentClient(...)
    await stack.enter_async_context(chat_client)
    ...
    agent = ChatAgent(...)
    await stack.enter_async_context(agent)
    response = await agent.run(...)
```

```python
# After
chat_client = FoundryChatClient(...)
...
agent = Agent(...)
response = await agent.run(...)
```

The `ASYNC_AZURE_CREDENTIAL` is module-level and not closed per-call (see Ch8 pattern).

---

### 5. `AggregateContextProvider` Removed

Ch9 beta had a try/except shim that defined a fallback `AggregateContextProvider` class to merge multiple providers. In GA, `Agent` accepts a list of providers directly via `context_providers=`:

```python
# Before
try:
    from agent_framework import AggregateContextProvider
except Exception:
    class AggregateContextProvider(ContextProvider):
        async def invoking(self, messages, **kwargs) -> Context: ...

context_provider: ContextProvider | AggregateContextProvider
if len(provider_chain) == 1:
    context_provider = provider_chain[0]
else:
    context_provider = AggregateContextProvider(provider_chain)

agent = ChatAgent(..., context_provider=context_provider, ...)
```

```python
# After
agent = Agent(..., context_providers=provider_chain, ...)
```

---

### 6. `ContextProvider.invoking()` → `before_run()` (Three Providers)

**`MemoryContextProvider`** (in `main.py`):

```python
# Before
class MemoryContextProvider(ContextProvider):
    def __init__(self, memory):
        self._memory = memory

    async def invoking(self, messages, **kwargs) -> Context:
        instructions = self._memory.contextual_instructions()
        return Context(instructions=instructions) if instructions else Context()
```

```python
# After
class MemoryContextProvider(ContextProvider):
    def __init__(self, memory):
        super().__init__(source_id="memory")
        self._memory = memory

    async def before_run(self, *, agent, session, context: SessionContext, state):
        instructions = self._memory.contextual_instructions()
        if instructions:
            context.instructions.append(instructions)
```

**`PersistentContextProvider`** and **`SemanticContextProvider`**: identical pattern — `invoking()` replaced with `before_run()`, `source_id` added to `super().__init__()`, `Context(instructions=...)` return replaced with `context.instructions.append(...)`. `SemanticContextProvider` reads the user message from `context.input_messages` (iterating reversed, finding the first `role == "user"` message).

---

### 7. `ChatMessage` → `Message` with Plain String Role

All `ChatMessage(role=..., text=...)` usages replaced with `Message(role=..., text=...)`. The role is now a plain string, not an enum, so `getattr(messages.role, "value", None)` becomes `messages.role` directly:

```python
# Before
if isinstance(messages, ChatMessage):
    message_role = getattr(messages.role, "value", None)
    if message_role == role:
        return messages.text

# After
if isinstance(messages, Message):
    if messages.role == role:
        return messages.text
```

---

### 8. `AIFunction` → `FunctionTool` in `_wrap_tool`

Ch9 has a bespoke `_wrap_tool` function that monkey-patches `tool.func` to add tracing. The isinstance check is updated:

```python
# Before
if isinstance(tool, AIFunction) and getattr(tool, "func", None) is not None:

# After
if isinstance(tool, FunctionTool) and getattr(tool, "func", None) is not None:
```

`FunctionTool` (returned by `@tool`) retains the `.func` attribute in GA 1.5.0, so the patching approach is unchanged.

---

### 9. `ToolMode` Type Annotation Removed

```python
# Before
tool_choice: ToolMode = {"mode": "required", "required_function_name": classify_issue_tool.name}

# After
tool_choice = {"mode": "required", "required_function_name": classify_issue_tool.name}
```

`ToolMode` no longer exists; the `default_options` dict is passed directly.

---

### 10. `AgentRunResponse` → `AgentResponse`

Both the try/except import shim and all type annotations updated:

```python
# Before
try:
    from agent_framework import AgentRunResponse
except Exception:
    AgentRunResponse = Any

# After — import at top level
from agent_framework import Agent, AgentResponse, ...
```

---

### 11. CLI Output Change (GA companion only)

Same fix as Chapters 4 and 5. The `main()` function previously called `run_thain()` (returns structured dict) and printed `json.dumps(response)`. Since DevUI is not guaranteed to work with GA, the CLI now prints the agent's Markdown triage card:

```python
# Before
response = run_thain(customer_message)
print(json.dumps(response, ensure_ascii=False))

# After
response_text, _ = run_thain_text(customer_message)
print(response_text)
```

`run_thain_text()` was already present in Ch9 (returns `tuple[str, str | None]` — text and trace_id). The interactive REPL path receives the same treatment.

---

## Test Changes

### `test_persistent_memory.py`

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. Added `_make_mock_context()` helper that returns a `MagicMock` with `ctx.metadata = {}` and `ctx.instructions = []`. 3 new provider tests added:
- `test_provider_source_id`
- `test_provider_injects_instructions_when_records_present`
- `test_provider_uses_metadata_customer_id`

### `test_semantic_provider.py`

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. Added `_make_mock_context()` helper with `ctx.input_messages` list. 3 new tests added:
- `test_provider_source_id`
- `test_no_instructions_when_mode_disabled`
- `test_no_instructions_when_no_results`

### `test_tracing.py` and `test_policy_tracing.py`

`@ai_function` → `@tool` on inline test functions. No structural changes.

**Result: 55/55 passed per version ✅**

---

## DevUI Note

DevUI is used in the book as a learning aid. The primary validation path for GA is the CLI and `pytest tests/`. The `tracing_enabled`/`instrumentation_enabled` shim in `launch_devui()` is retained as-is.

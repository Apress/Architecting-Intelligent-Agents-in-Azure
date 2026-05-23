# Chapter 7 — GA Migration Notes

**Chapter**: 7 — Thain Learns to Collaborate  
**Parts**: A, B, C  
**Migration**: MAF beta (`agent-framework-azure-ai==1.0.0b251016`) → GA 1.5.0 (`agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`)  
**Tests**: Part A 39/39 ✅ · Part B 44/44 ✅ · Part C 52/52 ✅

---

## Summary of Changes

Chapter 7 introduces multi-agent orchestration via a Blackboard pattern. The GA migration applies the same API changes as Chapters 4–6 across all three parts, plus a Chapter 7-specific fix in `triage_agent.py` where `AgenticTriageAgent` used `ChatAgent` with `ToolMode.NONE`.

---

## Files Changed Per Part

### All Three Parts (A, B, C)

| File | Change |
|------|--------|
| `requirements.txt` | Replaced beta packages with `agent-framework==1.5.0`, `agent-framework-core==1.5.0`, `agent-framework-foundry==1.5.0`, `agent-framework-devui==1.0.0b260519`; removed `azure-ai-agents` |
| `constraints.txt` | Replaced beta pins with GA pins |
| `tools/classifier.py` | `ai_function` → `tool` |
| `tools/action_tools.py` | `ai_function` → `tool` (all 3 occurrences) |
| `tools/search.py` | `ai_function` → `tool` |
| `memory/persistent_provider.py` | Full GA rewrite (see below) |
| `memory/semantic_provider.py` | Full GA rewrite (see below) |
| `main.py` | Full GA migration (see below) |
| `tests/test_persistent_memory.py` | Updated to GA `before_run` / mock context pattern |
| `tests/test_semantic_provider.py` | Updated to GA `before_run` / mock context pattern |
| `tests/test_tracing.py` | `ai_function` → `tool` |
| `tests/test_policy_tracing.py` | `ai_function` → `tool` |
| `tests/conftest.py` | Created (sys.path insertion for test isolation) |

### Parts B and C Only

| File | Change |
|------|--------|
| `agents/triage_agent.py` | `ChatAgent` → `Agent`; `chat_client=` → `client=`; removed `tool_choice=ToolMode.NONE`, `store=False` |

---

## Detailed Change: `memory/persistent_provider.py`

**Before** (beta):
```python
from agent_framework import ChatMessage, Context, ContextProvider

class PersistentContextProvider(ContextProvider):
    async def invoking(self, messages: Any, **kwargs: Any) -> Context:
        customer_id = kwargs.get("customer_id") or self._default_customer_id
        ...
        return Context(instructions=instructions)
```

**After** (GA):
```python
from agent_framework import ContextProvider, SessionContext

class PersistentContextProvider(ContextProvider):
    def __init__(self, *, memory_service, default_customer_id, lookup_limit=5):
        super().__init__(source_id="persistent-memory")
        ...

    async def before_run(self, *, agent, session, context: SessionContext, state: dict) -> None:
        customer_id = context.metadata.get("customer_id") or self._default_customer_id
        ...
        context.instructions.append(instructions)
```

---

## Detailed Change: `memory/semantic_provider.py`

Same pattern as `persistent_provider.py`:
- `invoking(messages, **kwargs) -> Context` → `before_run(*, agent, session, context: SessionContext, state) -> None`
- `super().__init__(source_id="semantic-recall")`
- User text extracted from `context.input_messages` (loop reversed, check `msg.role == "user"`)
- Append to `context.instructions` instead of returning `Context(instructions=...)`

---

## Detailed Change: `main.py`

### Imports
```python
# Removed:
from contextlib import AsyncExitStack
from agent_framework import AgentRunResponse, AggregateContextProvider, ChatAgent, ChatMessage, Context, ContextProvider, ToolMode, AIFunction
from agent_framework.azure import AzureAIAgentClient

# Added:
from agent_framework import Agent, AgentResponse, ContextProvider, FunctionTool, Message, SessionContext
from agent_framework_foundry import FoundryChatClient
```

### `MemoryContextProvider`
```python
# Before
async def invoking(self, messages, **kwargs) -> Context:
    return Context(instructions=...) if instructions else Context()

# After
def __init__(self, memory):
    super().__init__(source_id="short-term-memory")
    self._memory = memory

async def before_run(self, *, agent, session, context, state) -> None:
    if instructions:
        context.instructions.append(instructions)
```

### `_wrap_tool`
```python
# Before
if isinstance(tool, AIFunction) and getattr(tool, "func", None) is not None:

# After
if isinstance(tool, FunctionTool) and getattr(tool, "func", None) is not None:
```

### `AggregateContextProvider` removal
```python
# Before
context_provider: ContextProvider | AggregateContextProvider
if len(provider_chain) == 1:
    context_provider = provider_chain[0]
else:
    context_provider = AggregateContextProvider(provider_chain)

# After — removed entirely; pass list directly to Agent
```

### `AsyncExitStack` → credential `try/finally`
```python
# Before
async with AsyncExitStack() as stack:
    credential = DefaultAzureCredential(...)
    stack.push_async_callback(credential.close)
    chat_client = AzureAIAgentClient(project_endpoint=..., model_deployment_name=..., async_credential=...)
    await stack.enter_async_context(chat_client)
    ...
    agent = ChatAgent(chat_client=chat_client, ...)
    await stack.enter_async_context(agent)
    response = await agent.run(customer_message)

# After
credential = DefaultAzureCredential(...)
try:
    chat_client = FoundryChatClient(project_endpoint=..., model=..., credential=...)
    ...
    agent = Agent(client=chat_client, ...)
    response = await agent.run(customer_message)
finally:
    await credential.close()
```

### `ChatAgent` → `Agent` with `default_options`
```python
# Before
agent = ChatAgent(
    chat_client=chat_client,
    ...
    context_providers=context_provider,    # single or AggregateContextProvider
    tool_choice=ToolMode.REQUIRED(classify_issue_tool.name),
    store=True,
)

# After
agent = Agent(
    client=chat_client,
    ...
    context_providers=provider_chain,      # list directly
    default_options={"mode": "required", "required_function_name": classify_issue_tool.name},
)
```

**Part C conditional `ToolMode`** (when orchestrator handled recall/action):
```python
# Before
tool_choice = ToolMode.REQUIRED(classify_issue_tool.name)
if response_mode != "normal":
    chat_tools = []
    tool_choice = ToolMode.NONE
elif board.recall or board.knowledge or board.action:
    chat_tools = []
    tool_choice = ToolMode.NONE

# After
default_options = {"mode": "required", "required_function_name": classify_issue_tool.name}
if response_mode != "normal":
    chat_tools = []
    default_options = {}
elif board.recall or board.knowledge or board.action:
    chat_tools = []
    default_options = {}

agent = Agent(..., default_options=default_options if default_options else None)
```

### `_extract_latest_role_text`
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

### `ThainDevAgent.run` return type
```python
# Before: AgentRunResponse
# After: AgentResponse
```

### `launch_devui`
```python
# Before: tracing_enabled=tracing_enabled
# After:  instrumentation_enabled=tracing_enabled
```

---

## Part C Specific: `test_policy_tracing.py`

Part C's `_wrap_tool` returns `{"status": "denied", "approved": False, "reason": "policy_denied"}` for write-kind tools on policy deny (not `[]` as in Parts A/B). The test was updated accordingly:

```python
# Part A/B test assertion:
self.assertEqual(result, [])

# Part C test assertion:
self.assertIsInstance(result, dict)
self.assertEqual(result.get("status"), "denied")
self.assertFalse(result.get("approved"))
```

---

## Agents Added Per Part

| Part | New Agents | MAF changes? |
|------|-----------|--------------|
| A | None (orchestrator, safety_gate, triage_agent — Part A triage is `DeterministicTriageAgent`) | No |
| B | `knowledge_agent.py`, `recall_agent.py` | No — pure Python |
| C | `action_agent.py` | No — pure Python |

`AgenticTriageAgent` in `agents/triage_agent.py` (Parts B/C) used `ChatAgent` — migrated to `Agent` with `client=` param and `store=False`/`tool_choice=ToolMode.NONE` removed.

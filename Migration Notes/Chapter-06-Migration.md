# Chapter 6 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework-azure-ai==1.0.0b251016` (Oct 2025)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test results:** Part A 21/21 ✅ · Part B 34/34 ✅ · Part C 38/38 ✅

---

## What Chapter 6 Introduces

Chapter 6 adds **observability, governance, and audit** layers to Thain. The chapter is structured as three progressive parts:

- **Part A** — Structured tracing: `TraceRecorder`, `FileTraceSink`, `_wrap_tool()` for tool instrumentation, `redact_payload`, safety flags
- **Part B** — Policy engine: `PolicyEngine`, `apply_log_policy`, `detect_safety_flags`; `_wrap_tool()` extended with `policy_state` parameter for policy-gated tool invocation
- **Part C** — Error normalisation and audit: `normalize_error()`, `normalize_error_info()`, `TraceReplayService`; `run_thain_agent()` wrapped in `try/except/finally` to guarantee trace emission even on failure

All Chapter 5 components carry forward. The governance, observability, and audit modules have no MAF dependency — only `main.py`, providers, and tool files required changes.

---

## Package Changes

Identical across all three parts:

| Before (beta) | After (GA) |
|---|---|
| `agent-framework-azure-ai==1.0.0b251016` | `agent-framework==1.5.0` + `agent-framework-core==1.5.0` |
| — | `agent-framework-foundry==1.5.0` (split package) |
| `agent-framework-devui==1.0.0b251016` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-ai-agents>=1.1.0` | removed |

---

## API Changes

All changes from Chapters 2–5 apply here. Chapter 6 adds one additional pattern specific to its `_wrap_tool()` function.

---

### 1. `@ai_function` → `@tool` in All Tool Files

Same as Chapter 5 — all three tool files (`classifier.py`, `action_tools.py`, `search.py`) in each part updated.

```python
# Before
from agent_framework import ai_function

@ai_function(name="classify_issue", description="...")
def classify_issue_tool(...): ...
```

```python
# After
from agent_framework import tool

@tool(name="classify_issue", description="...")
def classify_issue_tool(...): ...
```

---

### 2. `AIFunction` → `FunctionTool` in `_wrap_tool()`

Chapter 6 introduces `_wrap_tool()` which wraps tool functions to record trace events. In beta it checked `isinstance(tool, AIFunction)`. In GA the decorator returns a `FunctionTool` — same `.func` attribute, same mutability, only the class name changed.

```python
# Before (all three parts)
from agent_framework import AIFunction

if isinstance(tool, AIFunction) and getattr(tool, "func", None) is not None:
```

```python
# After
from agent_framework import FunctionTool

if isinstance(tool, FunctionTool) and getattr(tool, "func", None) is not None:
```

The `tool.func = traced` mutation pattern works identically in GA.

---

### 3. All Chapter 2–5 Base Changes

`ChatAgent` → `Agent`, `AzureAIAgentClient` → `FoundryChatClient`, `AsyncExitStack` removed, `AggregateContextProvider` removed (list passed directly), `ToolMode.REQUIRED` → dict `default_options`, `AgentRunResponse` → `AgentResponse`, `tracing_enabled=` → `instrumentation_enabled=`, `ChatMessage` → `Message` with plain string role.

`PersistentContextProvider` and `SemanticContextProvider` both migrated to `before_run()` with `source_id` required in `super().__init__()`.

`MemoryContextProvider` (inline in `main.py`) also migrated to `before_run()` with `source_id="short-term-memory"`.

---

## Credential Cleanup

In beta, `AsyncExitStack` was used to close the `DefaultAzureCredential`. In GA it is replaced with an explicit `try/finally`:

```python
# Before
async with AsyncExitStack() as stack:
    credential = DefaultAzureCredential(...)
    stack.push_async_callback(credential.close)
    chat_client = AzureAIAgentClient(...)
    await stack.enter_async_context(chat_client)
    agent = ChatAgent(...)
    await stack.enter_async_context(agent)
    response = await agent.run(customer_message)
```

```python
# After
credential = DefaultAzureCredential(...)
try:
    chat_client = FoundryChatClient(project_endpoint=config.endpoint, model=config.model, credential=credential)
    agent = Agent(client=chat_client, ..., context_providers=provider_chain, default_options={...})
    response = await agent.run(customer_message)
finally:
    await credential.close()
```

In Part C the credential `try/finally` is nested inside the outer `try/except/finally` that guarantees trace emission.

---

## Test Changes

### `test_persistent_memory.py` (all three parts)

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. 3 new provider tests added:
- `test_provider_source_id`
- `test_provider_injects_instructions_when_records_present`
- `test_provider_uses_metadata_customer_id`

### `test_semantic_provider.py` (all three parts)

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. 3 new tests added:
- `test_provider_source_id`
- `test_no_instructions_when_mode_disabled`
- `test_no_instructions_when_no_results`

### `test_tracing.py` (all three parts)

`from agent_framework import ai_function` → `from agent_framework import tool`. Two `@ai_function` usages replaced with `@tool`.

### `test_policy_tracing.py` (Parts B and C)

`from agent_framework import ai_function` → `from agent_framework import tool`. `@ai_function(name="create_ticket")` → `@tool(name="create_ticket")`.

### `test_action_tools.py`, `test_agentic_search_tool.py`, `test_approvals.py`

No changes required — these tests have no `agent_framework` imports. `FunctionTool` is callable, so tool invocation tests work unchanged.

**Results: Part A 21/21 ✅ · Part B 34/34 ✅ · Part C 38/38 ✅**
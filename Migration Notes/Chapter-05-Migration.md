# Chapter 5 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework-azure-ai==1.0.0b251016` (Oct 2025)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 20/20 passed ✅

---

## What Chapter 5 Introduces

Chapter 5 adds **agentic tools and approval gates**. Thain gains write-capable action tools (`create_ticket`, `notify_team`, `retrieve_docs`) controlled by feature flags, and an approval service that intercepts write operations to require explicit human authorisation. New components introduced:

- `tools/action_tools.py` — factory producing three `@tool`-decorated action tools
- `tools/search.py` — factory producing the agentic `search_similar_complaints` tool
- `services/approvals.py` — `ApprovalService` + `requires_approval()` helper (no MAF dependency, unchanged)

All Chapter 4 components carry forward.

---

## Package Changes

Identical to Chapter 4:

| Before (beta) | After (GA) |
|---|---|
| `agent-framework-azure-ai==1.0.0b251016` | `agent-framework==1.5.0` |
| (split into separate package) | `agent-framework-foundry==1.5.0` |
| `agent-framework-devui==1.0.0b251016` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-ai-agents>=1.1.0` | removed |

---

## API Changes

All changes from Chapters 2–4 apply here. Chapter 5 adds one additional change specific to the new tool files.

---

### 1. `@ai_function` → `@tool` in All Tool Files

Chapter 5 introduces two new tool files, both using `@ai_function`. All occurrences across all three tool files are replaced.

**`tools/classifier.py`** — 1 decorator (same as previous chapters)

**`tools/action_tools.py`** — 3 decorators (one per action tool):

```python
# Before
from agent_framework import ai_function

@ai_function(name="create_ticket", description="...")
async def create_ticket(...): ...

@ai_function(name="notify_team", description="...")
async def notify_team(...): ...

@ai_function(name="retrieve_docs", description="...")
async def retrieve_docs(...): ...
```

```python
# After
from agent_framework import tool

@tool(name="create_ticket", description="...")
async def create_ticket(...): ...

@tool(name="notify_team", description="...")
async def notify_team(...): ...

@tool(name="retrieve_docs", description="...")
async def retrieve_docs(...): ...
```

**`tools/search.py`** — 1 decorator:

```python
# Before
from agent_framework import ai_function

@ai_function(name="search_similar_complaints", description="...")
async def search_similar_complaints(...): ...
```

```python
# After
from agent_framework import tool

@tool(name="search_similar_complaints", description="...")
async def search_similar_complaints(...): ...
```

Note: `FunctionTool` (returned by `@tool`) is directly callable, so existing tests that call the tool functions directly (`await create_ticket(...)`, `await retrieve_docs(...)`) continue to work without modification.

---

### 2. All Chapter 2–4 Base Changes

`ChatAgent` → `Agent`, `AzureAIAgentClient` → `FoundryChatClient`, `ToolMode.REQUIRED` → dict `default_options`, `AsyncExitStack` removed, `AggregateContextProvider` removed (list passed directly), `AgentRunResponse` → `AgentResponse`, `tracing_enabled=` → `instrumentation_enabled=`, `ChatMessage` → `Message` with plain string role.

`PersistentContextProvider` and `SemanticContextProvider` both migrated to `before_run()` with `source_id` required in `super().__init__()`.

---

## Test Changes

### `test_action_tools.py` and `test_agentic_search_tool.py`

No changes required — these tests call tool functions directly and have no `agent_framework` imports. `FunctionTool` is callable, so the tests work unchanged.

### `test_persistent_memory.py`

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. 3 new provider tests added:
- `test_provider_source_id`
- `test_provider_injects_instructions_when_records_present`
- `test_provider_uses_metadata_customer_id`

### `test_semantic_provider.py`

Migrated from `invoking()` to `before_run()` pattern. `from agent_framework import Context` removed. 3 new tests added:
- `test_provider_source_id`
- `test_no_instructions_when_mode_disabled`
- `test_no_instructions_when_no_results`

**Result: 20/20 passed ✅**

---

## CLI Output Change (GA companion only)

Same fix as Chapter 4. The agent is instructed to produce a Markdown triage card, but the beta CLI printed `json.dumps({"category": ..., "summary": ...})` instead. Since DevUI is not guaranteed to work with GA, the CLI should display what the chapter teaches.

`run_thain_text()` added as a thin wrapper returning `agent_response.text`. Both the single-message path and the interactive REPL now call this:

```python
# Before
response = run_thain(customer_message)
print(json.dumps(response, ensure_ascii=False))

# After
response = run_thain_text(customer_message)
print(response)
```

`run_thain()` is unchanged for any programmatic callers that need the structured dict.

---

## Bug Fixed in GA Version

Same regex bug as Chapters 2–4 — `rf"\\b{keyword}\\b"` → `rf"\b{keyword}\b"` in `tools/classifier.py`.

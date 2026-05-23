# Chapter 10 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework==1.0.0b260123` (Jan 2026)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 55/55 passed per sprint (Sp2.1 ✅ Sp2.2 ✅ Sp2.3 ✅)

---

## What Chapter 10 Introduces

Chapter 10 adds **performance, cost, and reliability hardening** across three sprints:

- `Sprint 2.1` — Observability instrumentation: token usage tracking, cost estimation, model name extraction, `llm.usage` trace events, `_resolve_usage()` / `_extract_usage()` / `_estimate_usage_heuristic()`, `AppInsightsTraceSink`
- `Sprint 2.2` — Optimisation: in-process response caching (`_RESPONSE_CACHE`, cache key hashing via SHA-256, TTL/eviction), instruction compaction (`_compact_instruction_text()`), response compaction (`_compact_response_sections()`), model profile env var (`THAIN_MODEL_PROFILE`)
- `Sprint 2.3` — Reliability hardening: `services/reliability.py` with circuit-breaker / timeout (`execute_dependency_call`, `DependencyFailure`, `DependencySuppressed`), degraded-mode fallback card (`_build_degraded_triage_card()`), graceful approval-status error handling, `fallback.used` trace events

Each sprint is an independent, testable snapshot of Thain at that stage.

---

## Package Changes

| Before (beta) | After (GA) |
|---|---|
| `agent-framework==1.0.0b260123` | `agent-framework==1.5.0` |
| `agent-framework-core==1.0.0b260123` | `agent-framework-core==1.5.0` |
| `agent-framework-azure-ai==1.0.0b260123` | `agent-framework-foundry==1.5.0` (split package) |
| `agent-framework-devui==1.0.0b260123` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-ai-agents>=1.1.0` | removed |
| Unused `agent-framework-*` plugins | removed |

---

## Shared API Changes (All Three Sprints)

All changes from Chapters 2–9 apply here — Ch10 is built on the same Ch9 v1.1 foundation. The key changes are summarised below; see the Ch9 migration notes for full before/after code blocks.

### 1. `@ai_function` → `@tool` in All Tool Files

`tools/classifier.py`, `tools/search.py`, `tools/action_tools.py` (3 decorators), plus test files where inline tools are defined.

### 2. `ChatAgent` → `Agent`

`agent = Agent(client=chat_client, ...)` — `chat_client=` renamed to `client=`.

### 3. `AzureAIAgentClient` → `FoundryChatClient`

```python
# Before
from agent_framework.azure import AzureAIAgentClient
chat_client = AzureAIAgentClient(project_endpoint=..., model_deployment_name=..., async_credential=...)

# After
from agent_framework_foundry import FoundryChatClient
chat_client = FoundryChatClient(project_endpoint=..., model=..., credential=...)
```

`model_deployment_name=` → `model=`. Credential shim and `AsyncExitStack` removed.

### 4. `ContextProvider.invoking()` → `before_run()`

`MemoryContextProvider`, `PersistentContextProvider`, and `SemanticContextProvider` all migrated:

```python
# After pattern (same in all providers)
class MemoryContextProvider(ContextProvider):
    def __init__(self, memory: ConversationMemory) -> None:
        super().__init__(source_id="memory")
        self._memory = memory

    async def before_run(self, *, agent, session, context: SessionContext, state) -> None:
        instructions = self._memory.contextual_instructions()
        if instructions:
            context.instructions.append(instructions)
```

`source_id=` is required in `super().__init__()`. `Context(instructions=...)` return value replaced with `context.instructions.append(...)`.

### 5. `AggregateContextProvider` Removed

`Agent(context_providers=provider_chain, ...)` — list passed directly; no wrapper class needed.

### 6. `ChatMessage` → `Message` with Plain String Role

All `ChatMessage` imports replaced with `Message`. Role is now a plain `str`, not an enum.

### 7. `AIFunction` → `FunctionTool` in `_wrap_tool`

```python
# Before
if isinstance(tool, AIFunction) and getattr(tool, "func", None) is not None:

# After
if isinstance(tool, FunctionTool) and getattr(tool, "func", None) is not None:
```

`FunctionTool.func` exists in GA 1.5.0 — the monkey-patching approach is unchanged.

### 8. `AgentRunResponse` → `AgentResponse`

Import updated; try/except import shim removed.

### 9. `ToolMode` Type Annotation Removed

`tool_choice = {"mode": "required", "required_function_name": ...}` — plain dict, no `ToolMode` annotation.

### 10. CLI Output Change

```python
# Before
response = run_thain(customer_message)
print(json.dumps(response, ensure_ascii=False))

# After
response_text, _ = run_thain_text(customer_message)
print(response_text)
```

`run_thain_text()` was already present in Ch9/Ch10 beta, returning `tuple[str, str | None]`.

---

## Sprint-Specific `Message` Occurrence Count

Ch10 builds additional synthetic `AgentResponse` objects (via `SimpleNamespace`) for fast-path branches. Each requires `Message(role="assistant", text=...)` in its `messages` list. The count grows per sprint as new paths are added:

| Sprint | `Message(role=...)` occurrences | New path added |
|---|---|---|
| 2.1 | 3 | approval-status path, safety path, message update |
| 2.2 | 4 | + cache-hit path |
| 2.3 | 5 | + degraded-fallback path |

---

## Sprint 2.2 — Caching Additions

Sprint 2.2 introduces an in-process response cache keyed by a SHA-256 fingerprint of the normalised message + model + search mode + feature flags.

The cache-hit path constructs a synthetic `AgentResponse` — the `Message` import is required here:

```python
# Cache hit — synthetic response (GA)
response = SimpleNamespace(
    text=cached_text,
    messages=[Message(role="assistant", text=cached_text)],
    metadata={},
)
```

Cache is controlled by env vars:
- `THAIN_ENABLE_CACHE` (default `false`)
- `THAIN_CACHE_TTL_SECONDS` (default 120)
- `THAIN_CACHE_MAX_ENTRIES` (default 200)

Write/approval/safety responses are never cached (`_cache_eligible_message()` and `_cache_eligible_response()` guard functions).

Sprint 2.2 also adds:
- `_compact_instruction_text()` — deduplicates repeated instruction fragments before sending to the agent
- `_compact_response_sections()` — trims Summary/Suggest sections to configurable char limits (env: `THAIN_RESPONSE_SUMMARY_MAX_CHARS`, `THAIN_RESPONSE_SUGGEST_MAX_CHARS`)
- `MODEL_PROFILE` env var (`THAIN_MODEL_PROFILE`) logged in `llm.usage` trace events

---

## Sprint 2.3 — Reliability Additions

Sprint 2.3 introduces `services/reliability.py` with a circuit-breaker and per-dependency timeout budget. The agent run is wrapped in `execute_dependency_call()`:

```python
from services.reliability import (
    DependencyFailure,
    DependencySuppressed,
    execute_dependency_call,
    timeout_ms_for_dependency,
)

try:
    response = await execute_dependency_call(
        "chat.agent.run",
        lambda: agent.run(customer_message),
        timeout_ms=timeout_ms_for_dependency("openai"),
    )
except (DependencyFailure, DependencySuppressed) as dep_exc:
    degraded_text = _build_degraded_triage_card(customer_message, board, dep_exc.dependency)
    response = SimpleNamespace(
        text=degraded_text,
        messages=[Message(role="assistant", text=degraded_text)],
        metadata={"degraded": True, "dependency": dep_exc.dependency},
    )
```

When the circuit is open or the call times out, `_build_degraded_triage_card()` produces a graceful triage card with a "service temporarily degraded" Suggest section rather than raising an exception.

The `fallback.used` trace event records every degraded-path invocation, including the dependency name and failure type.

Sprint 2.3 also hardens the approval-status path: Cosmos DB failures during approval lookup are caught and converted to a `fallback.used` event + user-facing message rather than propagating as unhandled exceptions.

---

## Test Changes

Ch10 tests are identical in structure to Ch9 tests — the same 55-test suite is reused across all three sprints. No sprint adds new tests; each sprint's test suite validates the cumulative feature set at that stage.

- `test_persistent_memory.py` — `before_run()` pattern, `_make_mock_context()` helper, 5 provider tests
- `test_semantic_provider.py` — `before_run()` pattern, `_make_mock_context()` with `ctx.input_messages`, 5 provider tests
- `test_tracing.py` / `test_policy_tracing.py` — `@tool` decorator on inline test functions
- All other tests unchanged from Ch9 v1.1 baseline

**Result: 55/55 passed per sprint ✅**

---

## Regex Bug Fixed (Same as Chapters 2–9)

`rf"\\b{re.escape(keyword)}\\b"` → `rf"\b{re.escape(keyword)}\b"` in `tools/classifier.py`.

---

## DevUI Note

DevUI is used in the book as a learning aid. The primary validation path for GA is the CLI and `pytest tests/`. The `tracing_enabled`/`instrumentation_enabled` parameter shim in `launch_devui()` is retained as-is via runtime inspection.

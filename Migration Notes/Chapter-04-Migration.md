# Chapter 4 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework-azure-ai==1.0.0b251016` (Oct 2025)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 13/13 passed ✅

---

## What Chapter 4 Introduces

Chapter 4 adds **semantic retrieval** via Azure AI Search and Azure OpenAI embeddings. Thain gains a `SemanticContextProvider` that embeds the user's message at each turn, searches a vector index for similar past complaints across all customers, and injects the results as context. New components introduced:

- `EmbeddingService` — wraps Azure OpenAI SDK to generate text embeddings
- `AzureSemanticSearchClient` — async Azure AI Search client for indexing and querying vectors
- `SemanticRecallService` — orchestrates embedding + search into a single recall capability
- `SemanticContextProvider` — ContextProvider subclass that surfaces semantic matches as agent instructions

All Chapter 3 components (Cosmos DB persistence, `PersistentContextProvider`) carry forward into Chapter 4. Note: `AggregateContextProvider` is removed in GA — the provider chain passes directly to `Agent(context_providers=[...])` as introduced in the Chapter 2 migration.

---

## Package Changes

| Before (beta) | After (GA) |
|---|---|
| `agent-framework-azure-ai==1.0.0b251016` | `agent-framework==1.5.0` |
| (split into separate package) | `agent-framework-foundry==1.5.0` |
| `agent-framework-devui==1.0.0b251016` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-ai-agents>=1.1.0` | removed (not needed in GA) |
| `azure-cosmos>=4.6.0` | unchanged |
| `pydantic>=2.8.0` | unchanged |
| `openai>=1.0.0` | unchanged |
| `azure-search-documents>=11.6.0` | unchanged |

---

## API Changes

All changes from Chapters 2 and 3 apply here. See [Chapter-02-Migration.md](Chapter-02-Migration.md) for the full base change list. Chapter 4 adds two additional changes specific to `SemanticContextProvider`.

---

### 1. `SemanticContextProvider` — New `ContextProvider` Interface

**Before:**
```python
from agent_framework import ChatMessage, Context, ContextProvider

class SemanticContextProvider(ContextProvider):
    def __init__(self, *, service, customer_id, lookup_limit=3, mode="semantic") -> None:
        self._service = service
        self._customer_id = customer_id
        self._lookup_limit = lookup_limit
        self._mode = mode

    async def invoking(self, messages: Any, **kwargs: Any) -> Context:
        if self._mode != "semantic":
            return Context()

        query_text = _extract_user_text(messages)  # extracted from messages arg
        if not query_text:
            return Context()

        try:
            records = await self._service.find_similar(...)
        except SemanticSearchError:
            return Context()

        if not records:
            return Context()

        return Context(instructions=instructions)
```

**After:**
```python
from agent_framework import ContextProvider, SessionContext

class SemanticContextProvider(ContextProvider):
    def __init__(self, *, service, customer_id, lookup_limit=3, mode="semantic") -> None:
        super().__init__(source_id="semantic-recall")   # required in GA
        self._service = service
        self._customer_id = customer_id
        self._lookup_limit = lookup_limit
        self._mode = mode

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: SessionContext,
        state: dict,
    ) -> None:
        if self._mode != "semantic":
            return

        # User message now comes from context.input_messages, not the messages argument
        query_text: str | None = None
        for msg in reversed(context.input_messages):
            if msg.role == "user" and msg.text:
                query_text = msg.text
                break
        if not query_text:
            return

        try:
            records = await self._service.find_similar(...)
        except SemanticSearchError:
            return   # early return instead of return Context()

        if not records:
            return

        context.instructions.append(instructions)   # mutate instead of return
```

Key differences:
- `source_id="semantic-recall"` required in `super().__init__()`
- `invoking(messages, **kwargs)` → `before_run(*, agent, session, context, state)`
- User message extracted from `context.input_messages` (list of `Message` objects with `.role` as plain string) rather than the `messages` argument
- `return Context(...)` → `context.instructions.append(...)` + implicit `return None`
- The `_extract_user_text()` helper that handled `ChatMessage` role enum is removed; `msg.role` is now a plain string (`"user"`)

---

### 2. `PersistentContextProvider` — Same Interface Change as Chapter 3

Chapter 4 carries the same `PersistentContextProvider` as Chapter 3. The identical migration applies:

- `super().__init__(source_id="persistent-memory")` added
- `invoking()` → `before_run()`
- `kwargs.get("customer_id")` → `context.metadata.get("customer_id")`
- `return Context(...)` → `context.instructions.append(...)` or `return`
- `_extract_user_text()` helper removed (was only used for a log message)

See [Chapter-03-Migration.md](Chapter-03-Migration.md) for full details.

---

### 3. `AggregateContextProvider` Removal

Same as Chapter 3. The `provider_chain` list is passed directly to `Agent`:

**Before:**
```python
from agent_framework import AggregateContextProvider

if len(provider_chain) == 1:
    context_provider = provider_chain[0]
else:
    context_provider = AggregateContextProvider(provider_chain)

agent = ChatAgent(..., context_providers=context_provider)
```

**After:**
```python
agent = Agent(..., context_providers=provider_chain)
```

---

### 4. All Chapter 2 Base Changes

`ChatAgent` → `Agent`, `AzureAIAgentClient` → `FoundryChatClient`, `@ai_function` → `@tool`, `ToolMode.REQUIRED` → dict `default_options`, `AsyncExitStack` removed, `AgentRunResponse` → `AgentResponse`, `tracing_enabled=` → `instrumentation_enabled=`, `ChatMessage` → `Message` with plain string role.

---

## Test Changes

### `test_semantic_provider.py`

The original 2 tests called `provider.invoking()` and checked the returned `Context` object:

```python
# Old (broken in GA)
from agent_framework import Context
context = await provider.invoking("New Wi-Fi issue")
self.assertIsInstance(context, Context)
self.assertIn("Connectivity", context.instructions or "")
```

The GA tests use a mock `SessionContext` with `input_messages` populated and check `context.instructions` mutation:

```python
# New (GA)
def _make_mock_context(user_message="New Wi-Fi issue"):
    msg = MagicMock()
    msg.role = "user"
    msg.text = user_message
    ctx = MagicMock()
    ctx.input_messages = [msg]
    ctx.instructions = []
    return ctx

ctx = _make_mock_context()
await provider.before_run(agent=None, session=None, context=ctx, state={})
self.assertIn("Connectivity", ctx.instructions[0])
```

**5 new tests added** covering the GA interface:
- `test_provider_source_id` — verifies `source_id` is set
- `test_instructions_emitted_when_results_available`
- `test_graceful_fallback_on_error`
- `test_no_instructions_when_mode_disabled`
- `test_no_instructions_when_no_results`
- `test_no_instructions_when_no_user_message`

### `test_persistent_memory.py`

`PersistentContextProviderTests` migrated to `before_run()` pattern. 3 new tests added:
- `test_provider_source_id`
- `test_provider_injects_instructions_when_records_present`
- `test_provider_uses_metadata_customer_id`

**Result: 13/13 passed ✅**

---

## CLI Output Change (GA companion only)

In the beta, `main()` printed `json.dumps({"category": ..., "summary": ...})` — the internal normalised dict, not the agent's response. Since the chapter instructs the agent to produce a Markdown triage card and DevUI is not guaranteed to work with GA, the GA companion code fixes this so the CLI shows what the chapter teaches.

`run_thain_text()` was added as a thin wrapper around `run_thain_agent()` that returns `agent_response.text`. Both the single-message path and the interactive REPL now call this instead of `run_thain()`:

```python
# Before (beta)
response = run_thain(customer_message)
print(json.dumps(response, ensure_ascii=False))   # prints {"category": ..., "summary": ...}

# After (GA companion)
response = run_thain_text(customer_message)
print(response)   # prints the Markdown triage card
```

`run_thain()` is unchanged and still returns the structured dict for any programmatic callers. The DevUI path (`ThainDevAgent`) is also unchanged.

---

## Bug Fixed in GA Version

Same regex bug as Chapters 2 and 3 — `rf"\\b{keyword}\\b"` → `rf"\b{keyword}\b"` in `tools/classifier.py`.

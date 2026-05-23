# Chapter 3 — MAF 1.5.0 GA Migration Notes

**Beta version used in book:** `agent-framework-azure-ai==1.0.0b251016` (Oct 2025)  
**GA version:** `agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`  
**Test result:** 7/7 passed ✅ (original 2 tests preserved + 5 new tests for the GA ContextProvider interface)

---

## What Chapter 3 Introduces

Chapter 3 adds **persistent memory** via Cosmos DB. Thain gains a `PersistentContextProvider` that loads prior complaint records from Cosmos DB on each turn, allowing the agent to reference conversation history that survives across sessions. This chapter uses everything from Chapter 2 and adds:

- `PersistentMemoryService` — coordinates Cosmos DB reads/writes
- `PersistentContextProvider` — ContextProvider subclass that surfaces Cosmos records as agent instructions
- `CosmosRepository` — async Cosmos DB client wrapper

---

## Package Changes

Same as Chapter 2:

| Before (beta) | After (GA) |
|---|---|
| `agent-framework-azure-ai==1.0.0b251016` | `agent-framework==1.5.0` |
| (split into separate package) | `agent-framework-foundry==1.5.0` |
| `agent-framework-devui==1.0.0b251016` | `agent-framework-devui==1.0.0b260519` (pinned tested beta) |
| `azure-cosmos>=4.6.0` | `azure-cosmos>=4.6.0` (unchanged) |
| `pydantic>=2.8.0` | `pydantic>=2.8.0` (unchanged) |

---

## API Changes

All changes from Chapter 2 apply here (see [Chapter-02-Migration.md](Chapter-02-Migration.md)). Chapter 3 adds one additional change specific to `PersistentContextProvider`.

---

### 1. `PersistentContextProvider` — New `ContextProvider` Interface

This is the only Chapter 3-specific MAF change. The `PersistentContextProvider` imports and interface change significantly.

**Before:**
```python
from agent_framework import ChatMessage, Context, ContextProvider

class PersistentContextProvider(ContextProvider):
    def __init__(self, *, memory_service, default_customer_id, lookup_limit=5) -> None:
        self._memory_service = memory_service
        self._default_customer_id = default_customer_id
        self._lookup_limit = lookup_limit

    async def invoking(self, messages: Any, **kwargs: Any) -> Context:
        customer_id = kwargs.get("customer_id") or self._default_customer_id
        try:
            records = await self._memory_service.fetch_recent(customer_id=customer_id, limit=self._lookup_limit)
        except PersistentStoreError:
            return Context()

        if not records:
            return Context()

        instructions = "Consider the following...\n" + "\n".join(formatted)
        return Context(instructions=instructions)
```

**After:**
```python
from agent_framework import ContextProvider, SessionContext

class PersistentContextProvider(ContextProvider):
    def __init__(self, *, memory_service, default_customer_id, lookup_limit=5) -> None:
        super().__init__(source_id="persistent-memory")   # required in GA
        self._memory_service = memory_service
        self._default_customer_id = default_customer_id
        self._lookup_limit = lookup_limit

    async def before_run(
        self,
        *,
        agent: Any,
        session: Any,
        context: SessionContext,
        state: dict,
    ) -> None:
        # Customer ID is passed via context.metadata instead of **kwargs
        customer_id = context.metadata.get("customer_id") or self._default_customer_id
        try:
            records = await self._memory_service.fetch_recent(customer_id=customer_id, limit=self._lookup_limit)
        except PersistentStoreError:
            return   # Early return, nothing to append

        if not records:
            return

        instructions = "Consider the following...\n" + "\n".join(formatted)
        context.instructions.append(instructions)   # Mutate context instead of returning
```

Key differences:
- `ChatMessage` and `Context` imports removed (both removed from GA `agent_framework`)
- `source_id="persistent-memory"` required in `super().__init__()`
- `invoking(messages, **kwargs)` → `before_run(*, agent, session, context, state)`
- Customer ID now from `context.metadata["customer_id"]` instead of `kwargs["customer_id"]`
- Return `Context(instructions=...)` → `context.instructions.append(...)` + `return None`
- On error/no records: `return Context()` → plain `return`

---

### 2. `AggregateContextProvider` Removal

Chapter 3 introduced provider chaining (short-term + long-term memory). In the beta, a helper class was needed.

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
# Just pass the list directly — Agent handles multiple providers natively
agent = Agent(..., context_providers=provider_chain)
```

`AggregateContextProvider` is removed in GA. `Agent.context_providers` accepts `Sequence[ContextProvider]` directly.

---

## Test Changes

The original `test_persistent_memory.py` tested `invoking()` and checked return type against `Context`:

```python
# Old test (broken in GA)
from agent_framework import Context
context = await provider.invoking([], customer_id="thain-demo")
self.assertIsInstance(context, Context)
self.assertFalse(context.instructions)
```

The GA test uses mock `SessionContext` and checks `context.instructions` mutation:

```python
# New test (GA)
context = _make_mock_context()  # MagicMock with context.instructions = []
await provider.before_run(agent=None, session=None, context=context, state={})
self.assertEqual(context.instructions, [])
```

**5 new tests added** covering the new interface patterns:
- `test_provider_source_id` — verifies `source_id` is set correctly
- `test_provider_injects_instructions_when_records_present` — confirms records produce context
- `test_provider_adds_no_instructions_when_no_records` — confirms no-op on empty results
- `test_provider_uses_metadata_customer_id` — confirms `context.metadata["customer_id"]` routing

**Result: 7/7 passed ✅**

---

## Suggested In-Chapter Note (1–2 sentences)

> The companion repository includes Chapter 3 updated for MAF 1.5.0 GA. `PersistentContextProvider` now implements `before_run()` instead of `invoking()`, mutating `context.instructions` directly; `AggregateContextProvider` is removed — pass a list of providers to `Agent` directly. See `COMPANION.md` for the complete migration reference.

---

## Architectural Observations

**`after_run()` for write-back.** The GA `ContextProvider` interface now has both `before_run()` and `after_run()`. An improved Chapter 3 pattern would move the persistent memory write-back (currently in `run_thain_agent` after `agent.run()`) into `PersistentContextProvider.after_run()`. This keeps `main.py` simpler and makes the memory lifecycle self-contained within the provider:

```python
async def after_run(self, *, agent, session, context, state) -> None:
    if context.response:
        # Store the result back to Cosmos DB here
        await self._memory_service.persist(...)
```

This is a meaningful architectural improvement available in GA that wasn't possible in the beta — worth highlighting to readers as a "try this yourself" extension.

**`context.metadata` for cross-provider data.** The beta passed `customer_id` as a `**kwargs` to `invoking()`. The GA `context.metadata` dict provides a cleaner, typed way for callers to pass per-invocation metadata to all providers. If you want to pass a customer ID to `PersistentContextProvider`, set `context.metadata["customer_id"]` in an earlier provider or via a middleware. This is a better separation of concerns.

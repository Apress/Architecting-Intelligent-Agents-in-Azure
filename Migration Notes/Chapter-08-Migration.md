# Chapter 8 — GA Migration Notes

**Chapter**: 8 — Thain Goes Live  
**Sprints**: 1 through 6  
**Migration**: MAF beta (`agent-framework==1.0.0b260123`) → GA 1.5.0 (`agent-framework==1.5.0` + `agent-framework-foundry==1.5.0`)  
**Tests**: Sprint 1 52/52 ✅ · Sprint 2 52/52 ✅ · Sprint 3 52/52 ✅ · Sprint 4 52/52 ✅ · Sprint 5 53/53 ✅ · Sprint 6 54/54 ✅

---

## Summary of Changes

Chapter 8 ships Thain as a production system: FastAPI HTTP layer, CI/CD pipeline, IaC, Azure AI Search for doc retrieval, and a full Cosmos-backed approval workflow. The GA migration applies the same API changes as Chapters 5–7 across all six sprints, plus Sprint 6-specific changes to the approval service, action tools, and test fixtures.

Each sprint is a cumulative codebase — Sprint N is a standalone copy that adds to Sprint N-1. Files not changed by a sprint can be bulk-copied from the previous sprint's GA directory.

---

## Files Changed Per Sprint

### All Sprints (1–6)

| File | Change |
|------|--------|
| `requirements.txt` | Replaced `agent-framework==1.0.0b260123` with `agent-framework==1.5.0` + `agent-framework-core==1.5.0` + `agent-framework-foundry==1.5.0` + `agent-framework-devui==1.0.0b260519`; removed `azure-ai-agents` |
| `constraints.txt` | Replaced beta pins (`agent-framework==1.0.0b260123`, etc.) with GA pins: `agent-framework==1.5.0`, `agent-framework-core==1.5.0`, `agent-framework-foundry==1.5.0`, `agent-framework-devui==1.0.0b260519`, `azure-ai-contentsafety>=1.0.0`, `azure-monitor-opentelemetry==1.4.0` |
| `tools/classifier.py` | `ai_function` → `tool` |
| `tools/action_tools.py` | `ai_function` → `tool` (all decorated functions); see Sprint 6 below for additional changes |
| `tools/search.py` | `ai_function` → `tool` |
| `memory/persistent_provider.py` | Full GA rewrite — `invoking` → `before_run`; `source_id` required; `context.instructions.append(...)` |
| `memory/semantic_provider.py` | Full GA rewrite — same pattern as `persistent_provider.py` |
| `main.py` | Full GA migration per sprint (see Detailed Changes below) |
| `tests/test_persistent_memory.py` | Updated to GA `before_run` / mock `SessionContext` pattern |
| `tests/test_semantic_provider.py` | Updated to GA `before_run` / mock `SessionContext` pattern |
| `tests/test_tracing.py` | `ai_function` → `tool`; `AIFunction` → `FunctionTool` |
| `tests/test_policy_tracing.py` | `ai_function` → `tool`; `AIFunction` → `FunctionTool` |
| `tests/conftest.py` | Created (sys.path insertion for test isolation) |

### Sprint 5 — New Files (no MAF imports; copied directly from beta)

| File | Change |
|------|--------|
| `config/settings.py` | Added `AzureAIDocsSearchConfig`, `load_docs_search_config` |
| `memory/docs_search_client.py` | New — pure Azure SDK (no MAF) |
| `memory/docs_service.py` | New — pure Python (no MAF) |
| `tests/test_docs_service.py` | New — pure Python (no MAF) |

### Sprint 6 — New/Updated Files

| File | Change |
|------|--------|
| `config/settings.py` | Added `ApprovalStoreConfig`, `ApprovalWorkflowConfig`, `load_approval_store_config`, `load_approval_workflow_config` — no MAF imports, copied from beta |
| `services/approval_store.py` | New — pure Azure SDK + Cosmos (no MAF), copied from beta |
| `services/approvals.py` | **Full replacement** — old stub removed; replaced with `ApprovalOutcome` dataclass, `with_context`, `try_mark_executed`, full Cosmos-backed implementation |
| `tools/action_tools.py` | Restructured — added `_execute_ticket_action`, `_execute_notify_action`, `execute_approved_action`; approval flow now uses `ApprovalOutcome` (object, not bool); `@ai_function` → `@tool` |
| `tests/test_approvals.py` | Updated — `ApprovalService(enabled=True, prompt=...)` → `FakeApprovalService`; `reason` assertion updated (`"approval_not_provided"` → `"approval_denied"`) |
| `tests/test_action_tools.py` | Updated — added `FakeDocsService`, `FailingDocsService`; `create_action_tools(cfg)` → `create_action_tools(cfg, docs_service=FakeDocsService())`; added `test_retrieve_docs_returns_trace_error_on_failure` |

---

## Detailed Change: `main.py` (applies to all sprints)

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
# Before (beta)
async def invoking(self, messages, **kwargs) -> Context:
    return Context(instructions=...) if instructions else Context()

# After (GA)
def __init__(self, memory):
    super().__init__(source_id="short-term-memory")
    self._memory = memory

async def before_run(self, *, agent, session, context: SessionContext, state) -> None:
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
if len(provider_chain) == 1:
    context_provider = provider_chain[0]
else:
    context_provider = AggregateContextProvider(provider_chain)
agent = ChatAgent(..., context_providers=context_provider)

# After — pass list directly
agent = Agent(..., context_providers=provider_chain)
```

### `AsyncExitStack` removal

Chapter 8 uses a module-level `ASYNC_AZURE_CREDENTIAL` pattern (introduced in Sprint 2+) — no `AsyncExitStack` needed in any sprint.

```python
# Module-level
ASYNC_AZURE_CREDENTIAL = get_azure_credential(AUTH_MODE, async_credential=True)
SYNC_AZURE_CREDENTIAL  = get_azure_credential(AUTH_MODE, async_credential=False)

# Inside run_thain_agent (no stack)
chat_client = FoundryChatClient(
    project_endpoint=config.endpoint,
    model=config.model,
    credential=ASYNC_AZURE_CREDENTIAL,
)
```

### `ChatAgent` → `Agent`

```python
# Before
agent = ChatAgent(
    chat_client=chat_client,
    ...
    context_providers=context_provider,
    tool_choice=ToolMode.REQUIRED(classify_issue_tool.name),
    store=True,
)

# After
agent = Agent(
    client=chat_client,
    ...
    context_providers=provider_chain,
    default_options={"mode": "required", "required_function_name": classify_issue_tool.name},
)
```

### Conditional `ToolMode` → `default_options` (Sprint 4+)

```python
# Before
tool_choice = ToolMode.REQUIRED(classify_issue_tool.name)
if board.recall or board.knowledge or board.action:
    tool_choice = ToolMode.NONE
    chat_tools = []

# After
default_options = {"mode": "required", "required_function_name": classify_issue_tool.name}
if (board.recall is not None) or (board.knowledge is not None) or (board.action is not None):
    default_options = {}
    chat_tools = []

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

### `AgentRunResponse` → `AgentResponse`

```python
# Before
async def run_thain_agent(...) -> Tuple[Dict[str, Any], AgentRunResponse]:

# After
async def run_thain_agent(...) -> Tuple[Dict[str, Any], AgentResponse]:
```

### `launch_devui` — tracing parameter rename

```python
# Before
serve_devui(..., tracing_enabled=tracing_enabled)

# After — introspects signature at runtime to support both names:
if "tracing_enabled" in params:
    serve_kwargs["tracing_enabled"] = tracing_enabled
elif "instrumentation_enabled" in params:
    serve_kwargs["instrumentation_enabled"] = tracing_enabled
```

---

## Detailed Change: Sprint 6 `services/approvals.py`

The beta `ApprovalService` was a simple prompt-based stub (`prompt: Callable`, `request_approval` returned `bool`). Sprint 6 replaces it entirely with a Cosmos-backed service.

```python
# Before (beta / Sprint 5 GA stub)
class ApprovalService:
    def __init__(self, enabled: bool, prompt: Callable[[str], str] | None = None, ...):
        ...
    async def request_approval(self, tool_name, payload) -> bool:
        ...

# After (Sprint 6 GA)
@dataclass(frozen=True)
class ApprovalOutcome:
    approval_id: str
    tool_name: str
    approved: bool
    status: str  # "approved", "pending", "denied", "expired"
    reason: str | None = None
    expires_at: str | None = None
    decided_at: str | None = None
    tool_args_hash: str | None = None

class ApprovalService:
    def __init__(self, *, enabled, store, workflow, on_request, on_decision):
        ...
    def with_context(self, *, trace_id, run_id, turn_id, on_request, on_decision) -> ApprovalService:
        ...
    async def request_approval(self, tool_name, payload) -> ApprovalOutcome:
        ...
    async def try_mark_executed(self, approval_id, executor_run_id=None) -> bool:
        ...
```

---

## Detailed Change: Sprint 6 `tools/action_tools.py`

```python
# Before (Sprint 5 GA)
from agent_framework import tool
from services.approvals import ApprovalService, requires_approval

def create_action_tools(action_config, approval_service=None) -> list[Any]:
    # request_approval returned bool; checked `if not approved`
    approved = await approval_service.request_approval(...)
    if not approved:
        return {"status": "denied", ...}

# After (Sprint 6 GA)
from agent_framework import tool
from services.approvals import ApprovalOutcome, ApprovalService, requires_approval

def _execute_ticket_action(payload, approval_id=None) -> Dict[str, Any]: ...
def _execute_notify_action(payload, approval_id=None) -> Dict[str, Any]: ...
def execute_approved_action(tool_name, payload, approval_id=None) -> Dict[str, Any]: ...

def create_action_tools(action_config, approval_service=None, docs_service=None) -> list[Any]:
    # request_approval returns ApprovalOutcome; check outcome.approved + outcome.status
    approval_outcome = await approval_service.request_approval(...)
    if not approval_outcome.approved:
        reason = "approval_pending" if approval_outcome.status == "pending" else ...
        return {"status": approval_outcome.status, "reason": reason, ...}
    if not await approval_service.try_mark_executed(approval_outcome.approval_id):
        return {"status": "denied", "reason": "approval_already_executed", ...}
    return _execute_ticket_action(payload, approval_id=approval_outcome.approval_id)
```

---

## Sprint 6 Test Fixture Changes

### `tests/test_approvals.py`

- **Removed**: `ApprovalService(enabled=True, prompt=lambda _: "n")` — old signature no longer valid
- **Added**: `FakeApprovalService` with `request_approval` returning `ApprovalOutcome` and `try_mark_executed` returning bool
- **Updated**: `reason` assertion changed from `"approval_not_provided"` → `"approval_denied"` (now derived from `ApprovalOutcome.status`)
- **Updated**: `test_read_tool_bypasses_approval` now passes `docs_service=FakeDocsService()` (required — `retrieve_docs` now delegates to real service)

### `tests/test_action_tools.py`

- **Added**: `FakeDocsService` (returns stub corpus) and `FailingDocsService` (raises `RuntimeError`)
- **Updated**: `test_retrieve_docs_returns_top_k` now passes `docs_service=FakeDocsService()` — without it, tool returns a single `_trace_error` dict
- **Added**: `test_retrieve_docs_returns_trace_error_on_failure` — verifies error encapsulation when `docs_service.retrieve` raises

---

## Sprint-by-Sprint What's New

| Sprint | New Functionality | New Files |
|--------|-----------------|-----------|
| 1 | Base Thain: classify, triage, policy, tracing | — |
| 2 | FastAPI HTTP layer, CORS, health endpoints | `api/app.py` |
| 3 | IaC (11-stage PowerShell deployment) | PowerShell scripts (no MAF) |
| 4 | Multi-agent orchestration (Blackboard) | `orchestration/runner.py`, `orchestration/blackboard.py`, `agents/` |
| 5 | Azure AI Search doc retrieval (`retrieve_docs`) | `config/settings.py` (extended), `memory/docs_search_client.py`, `memory/docs_service.py` |
| 6 | Cosmos-backed approval workflow | `config/settings.py` (extended), `services/approval_store.py`, `services/approvals.py` (full rewrite), `tools/action_tools.py` (restructured) |

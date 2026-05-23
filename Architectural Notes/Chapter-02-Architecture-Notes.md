# Chapter 2 Architecture Notes

## Chapter anchor

Chapter 2 turns Thain from an idea into a working Python agent. The chapter introduces the first complete runtime: configuration, short-term memory, a deterministic classifier tool, an Agent Framework agent backed by Microsoft Foundry, and three execution modes for local use.

The GA companion code updates the framework surface to `Agent`, `FoundryChatClient`, `@tool`, and the `before_run` context provider hook. Those changes are covered in the migration notes. This document focuses on the architectural meaning of the chapter.

## Architectural lens

The most important architectural decision in Chapter 2 is the separation between model reasoning and application control.

Thain uses GPT-4o to reason about the complaint, but the application still owns the surrounding control surfaces: configuration loading, tool registration, memory injection, response parsing, and fallback behavior. This is the first step toward a production-grade agent. The model is powerful, but it is not the whole system.

The `MemoryContextProvider` is the key pattern. Instead of manually stitching memory into every prompt, the agent runtime calls a provider before the model run. In the GA code, that provider appends context through `context.instructions`. This turns memory injection into a runtime pipeline concern rather than a prompt-string concern.

That small pattern scales through the rest of the book. Chapter 3 adds persistent memory. Chapter 4 adds semantic recall. Chapter 6 adds governance and observability. Chapter 7 carries the same idea into multi-agent orchestration.

## Current production trend: control is moving out of prompts

As of May 2026, agent frameworks are increasingly moving production control out of natural-language prompts and into explicit runtime surfaces. The common direction is clear:

- tools define callable capabilities
- context providers or sessions carry state
- structured outputs protect downstream code
- guardrails check inputs, outputs, and tool calls
- traces record what happened during the run
- human review gates risky work

OpenAI's current Agents SDK guidance describes the SDK path as appropriate when the application owns orchestration, tool execution, state, and approvals. Microsoft Agent Framework follows the same broad direction by separating the standard `Agent` abstraction from provider-specific clients such as `FoundryChatClient`.

For Thain, the lesson is simple: use prompts for behavioral guidance, but use code for contracts, state, policy, validation, and side effects.

## Design implications for Thain

Chapter 2 gives Thain one bounded responsibility: triage a single complaint and return a structured result. That boundary is valuable. A narrow first agent is easier to test, observe, and govern. If the first version tried to retrieve documents, approve actions, create tickets, and coordinate specialists, every failure would be harder to diagnose.

The classifier is intentionally simple, but it serves an important purpose. It gives the model a deterministic reference point. In production systems, deterministic helpers are useful because they provide stable checks around probabilistic model behavior.

The short-term memory buffer should also be understood carefully. It is useful for interactive continuity, but it is not durable truth. It disappears when the process exits and has no strong tenant boundary. That is acceptable in Chapter 2 because the goal is to teach the agent runtime. Chapter 3 introduces the durable memory boundary.

The response parser and fallback path are also production-shaped. Even when the model is instructed to return JSON, the application validates the output and has a deterministic fallback. This habit becomes more important later when model output feeds APIs, tools, policy checks, and audit records.

Finally, credential lifecycle is part of the architecture. The GA code explicitly closes the async Azure credential after the agent run. That looks like a small implementation detail, but it is a runtime reliability concern. Long-lived services, local tools, and tests all need clear ownership of external resources.

## Beyond the chapter

The book keeps Chapter 2 focused on the first working agent. The companion repo can point readers toward the production concerns that naturally follow.

### 1. Output schemas

Chapter 2 parses JSON manually. A production version should move toward explicit schema validation with Pydantic models, framework-native structured output, or a repair-and-retry path for malformed responses.

The goal is not perfect formatting. The goal is to prevent unvalidated model text from silently becoming application state.

### 2. Tool risk levels

The classifier is read-only. Later tools will retrieve documents, create tickets, and notify teams. A production tool registry should classify tools by risk:

- read-only
- write with approval
- write without approval
- external communication
- destructive or irreversible

Even though Chapter 2 has only one simple tool, readers can start seeing why tool metadata matters.

### 3. Context budget rules

The short-term memory buffer renders a small list into instructions. That works because the buffer is tiny. Real systems need explicit context budget rules:

- how many memories can be injected
- which memories win when space is limited
- when old turns should be summarized
- how source labels are preserved
- how tenant and user boundaries are enforced

Context affects cost, latency, and answer quality. It should be managed deliberately.

### 4. Guardrails at the correct boundary

Chapter 2 does not need a heavy guardrail system, but the architecture should leave room for one. Current agent guidance increasingly distinguishes agent-level input/output guardrails from tool-level guardrails. That distinction matters once tools can create side effects.

For Thain, this becomes concrete in Chapters 5 and 6.

### 5. Trace-first development

The Dev UI is introduced as a learning aid, but it also teaches a production habit: inspect the reasoning loop, tool calls, and outputs while developing. In later chapters, this grows into structured tracing, audit replay, and trace-based evaluation.

## Reader extension ideas

- Replace the JSON parsing fallback with a Pydantic response model.
- Add a `tool_kind` field for the classifier, even though it is read-only, to prepare for later tool governance.
- Add a session identifier to `ConversationMemory` so short-term memory is explicitly scoped.
- Add a test proving invalid model JSON falls back to deterministic classification.

## References

- Microsoft Foundry provider guidance for Agent Framework: https://learn.microsoft.com/en-us/agent-framework/agents/providers/microsoft-foundry
- OpenAI Agents SDK guide: https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK guardrails documentation: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI trace grading guide: https://developers.openai.com/api/docs/guides/trace-grading

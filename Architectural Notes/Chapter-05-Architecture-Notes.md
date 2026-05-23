# Chapter 5 Architecture Notes

## Chapter anchor

Chapter 5 gives Thain tools. The agent moves from analysis and retrieval into controlled action: searching similar complaints on demand, retrieving supporting documents, creating tickets, notifying teams, and requiring approval before write actions take effect.

This is the point where agent architecture becomes operationally serious. Once an agent can affect external systems, the design must separate reasoning, intent, approval, and execution.

## Architectural lens

The most important architectural decision in Chapter 5 is the read/write tool split.

Read tools gather evidence. Write tools create side effects. Those two categories should not share the same governance path. Retrieval can usually be available by default inside a scoped boundary. Ticket creation, notification, refunds, deletions, and workflow triggers require stricter controls.

The approval service keeps this distinction visible. The agent can reason about an action, but the system decides whether the action can execute. This is the right model for enterprise systems: autonomy is granted at the boundary, not assumed inside the model.

## Current production trend: tools are becoming governed contracts

As of May 2026, agent platforms increasingly treat tools as typed, governed contracts rather than arbitrary functions exposed to a model. Modern guidance emphasizes tool schemas, tool-call traces, guardrails, approval modes, and explicit human review for sensitive operations.

This is also where protocol discussions such as MCP become relevant. MCP can standardize how tools and external data are exposed to agents, but it does not replace application governance. A dangerous tool remains dangerous whether it is called directly, through MCP, or through another integration layer.

For Thain, the important idea is not only "the agent can call a tool." It is "each tool has a contract, a risk level, an approval rule, and a traceable outcome."

## Design implications for Thain

Chapter 5 adds outcome fields to complaint records before introducing the tools that populate them. That sequencing is good architecture. The system first creates a place to record what happened, then gives the agent a way to make something happen.

Agentic retrieval also becomes explicit. Earlier semantic retrieval ran as context enrichment. In Chapter 5, search becomes a tool the agent can choose. This makes evidence gathering observable. A tool call has inputs, outputs, timing, errors, and traceability. Hidden retrieval can be useful, but explicit retrieval is easier to debug.

The approval gate also creates a clean separation:

- The model proposes or requests.
- The approval service decides whether execution is allowed.
- The tool returns a structured outcome.
- The memory and trace layers can record the result.

This protects the system from treating model confidence as authorization.

## Beyond the chapter

The chapter uses lightweight approvals and stubbed integrations so readers can focus on the architecture. The companion repo can point toward the next production concerns.

### 1. Idempotency

Write tools should be idempotent. If the same approval or retry is processed twice, the system should not create duplicate tickets or send duplicate notifications. Chapter 8 later strengthens this through durable approval state.

### 2. Tool input validation

Tool schemas are not enough. Inputs should be validated against business rules before execution. For example:

- ticket priority must be from an allowed set
- notification target must be approved
- customer identifier must match the authenticated scope
- document retrieval must obey tenant filters

### 3. Approval context

Human approvers need enough context to make a decision. A production approval request should include the proposed action, reason, source evidence, risk level, trace ID, expiry, and expected side effect.

### 4. Compensating actions

Some systems cannot undo side effects. Others can. Tool design should state whether a side effect is reversible and whether a compensating action exists.

### 5. Tool abuse and prompt injection

As tools become more powerful, prompt injection risk increases. A retrieved document or user message may try to influence tool execution. Tool guardrails should evaluate the final tool arguments, not only the original user input.

## Reader extension ideas

- Add a `tool_kind` registry with `read`, `write`, and `external_notify` categories.
- Add idempotency keys to write-tool payloads.
- Add an approval record model that stores trace ID, proposed action, and expiry.
- Add tests proving read tools bypass approval while write tools require it.

## References

- OpenAI Agents SDK guardrails documentation: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI Agents SDK tracing documentation: https://openai.github.io/openai-agents-python/tracing/
- Model Context Protocol specification: https://modelcontextprotocol.io/specification
- Microsoft Agent Framework sequential orchestration and tool approval concepts: https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/sequential
- Azure Well-Architected Framework: https://learn.microsoft.com/en-us/azure/well-architected/

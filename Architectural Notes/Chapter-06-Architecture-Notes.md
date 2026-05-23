# Chapter 6 Architecture Notes

## Chapter anchor

Chapter 6 makes trust an explicit architectural layer. Thain already reasons, remembers, retrieves, and acts. This chapter adds structured tracing, governance rules, redaction, policy enforcement, normalized failures, and audit replay.

The chapter is intentionally sequenced in three parts: observe first, govern second, audit and normalize failures third.

## Architectural lens

The most important architectural decision in Chapter 6 is that trust is implemented outside the model.

The model does not decide what should be logged, what should be redacted, whether a tool is allowed, or how a failure should be classified. Those are application responsibilities. The chapter's `_wrap_tool` pattern is important because it instruments and governs tool execution without rewriting every tool.

This creates a reusable trust layer. The governance, observability, and audit modules carry little or no dependency on the agent framework, so they can survive framework changes and later multi-agent expansion.

## Current production trend: agent observability is moving toward standard telemetry

As of May 2026, agent observability is shifting from custom JSON logs toward structured traces, spans, events, and metrics. OpenTelemetry now has semantic conventions for generative AI systems, including model calls and agent/framework spans. Microsoft Foundry also provides tracing guidance for agent frameworks and can send trace data to Azure Monitor Application Insights.

The direction is clear: agent traces should become part of normal production telemetry, not separate debug artifacts.

That does not mean every prompt and response should be logged. Production observability must balance traceability with privacy, retention, and cost.

## Design implications for Thain

Chapter 6 starts with deterministic trace identity: run, trace, and turn IDs. That gives every decision a place in time and a correlation boundary.

The trace recorder then captures what happened as a sequence of events. The important production property is not just that logs exist. It is that the trace can reconstruct a turn: inputs, tool calls, policy decisions, denials, failures, and final output.

Governance is added after visibility. That order is practical. You cannot enforce a boundary well if you cannot see whether it was crossed.

Failure normalization is equally important. A policy denial, approval rejection, search outage, content safety issue, and unhandled exception are different events. If they all look like "agent failed," operators cannot respond correctly.

## Beyond the chapter

The chapter creates a strong local trust layer. The companion repo can point readers toward production hardening around telemetry and governance.

### 1. Trace schema versioning

Trace events should have a schema version. Agent traces evolve quickly as tools, policies, and models change. Versioning keeps audit replay and dashboards stable.

### 2. Redaction policy as code

Redaction rules should be reviewed like security-sensitive code. They should define which fields are blocked, truncated, hashed, or allowed, and they should be tested with realistic payloads.

### 3. Telemetry sampling

Full-fidelity traces are valuable, but they can become expensive. Production systems often need sampling rules, exception-based capture, or higher retention only for incidents.

### 4. Separation of denial and failure

A denied action is not a failed action. This distinction should appear in traces, user responses, metrics, and alerts.

### 5. Audit replay boundaries

Replay should reconstruct decisions, not re-execute side effects. A production replay service must never accidentally recreate tickets or notifications.

## Reader extension ideas

- Add a trace schema version to every trace artifact.
- Add tests that verify sensitive fields are redacted before writing traces.
- Add an alert rule for repeated policy denials by tool type.
- Add a replay mode that reads traces and produces a human-readable incident summary.

## References

- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- Azure AI Foundry tracing for agents: https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/tracing
- Configure tracing for AI agent frameworks in Microsoft Foundry: https://learn.microsoft.com/en-us/azure/ai-foundry/observability/how-to/trace-agent-framework
- OpenAI Agents SDK tracing documentation: https://openai.github.io/openai-agents-python/tracing/
- Azure Well-Architected Framework operational excellence: https://learn.microsoft.com/en-us/azure/well-architected/

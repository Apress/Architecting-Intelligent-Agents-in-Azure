# Chapter 1 Architecture Notes

## Chapter anchor

Chapter 1 establishes Thain as more than a prompt wrapped around a model. The chapter frames an agent as a system that can reason, use tools, retain context, and eventually operate under production constraints such as governance, observability, reliability, and cost control.

At this stage, the code footprint is intentionally light. The chapter uses Azure AI Foundry and a few prompt/listing examples to give readers a working mental model before the Python implementation begins in Chapter 2.

## Architectural lens

The most important architectural decision in Chapter 1 is the capability arc:

1. Start with a single bounded agent.
2. Add short-term and persistent memory.
3. Add semantic retrieval.
4. Add tools and approvals.
5. Add observability, governance, and audit.
6. Add multi-agent coordination.
7. Deploy, evaluate, optimize, and harden.

That order matters. A common failure mode in agent projects is to jump directly to multi-agent orchestration, tool use, or production hosting before the system has a clear unit of responsibility. Chapter 1 avoids that by giving Thain one job first: read feedback and produce useful support insight.

For production teams, this is the right shape. Agentic architecture should grow from a narrow, testable role into a governed system. The agent's autonomy should increase only after the system has boundaries, telemetry, and recovery paths.

## Current production trend: agent runtimes are becoming application runtimes

As of May 2026, the strongest trend across agent platforms is the move from "model call plus glue code" to structured agent runtimes. Modern agent frameworks are converging around the same primitives:

- explicit agent definitions
- tool execution
- session or state handling
- handoffs or specialist routing
- guardrails
- tracing
- human review for risky work

OpenAI's current Agents SDK guidance describes agents as applications that plan, call tools, collaborate across specialists, and keep enough state for multi-step work. It also draws a clear boundary between direct model APIs and SDK-owned orchestration, state, tools, and approvals. Microsoft Agent Framework follows a similar direction by separating the core agent abstraction from provider integrations such as Microsoft Foundry.

This trend supports the book's framing: the interesting engineering problem is not "how do I call a model?" It is "where do I put control, state, evidence, permissions, and failure handling?"

## Design implications for Thain

Chapter 1's system map is useful because it separates capability from production quality.

Capability answers:

- Can Thain classify feedback?
- Can it remember prior complaints?
- Can it retrieve related issues?
- Can it use tools?
- Can multiple agents collaborate?

Production quality answers:

- Can we explain what happened?
- Can we stop unsafe actions?
- Can we replay or audit a decision?
- Can we validate a deployment?
- Can we measure quality, cost, and latency?
- Can we degrade safely when dependencies fail?

This distinction should stay visible throughout the repository. Each later chapter adds a capability, but the architecture becomes valuable only when the capability is paired with explicit control surfaces.

## Beyond the chapter

The book cannot cover every production concern in Chapter 1, and it should not. The following topics are worth touchpointing in the companion repo because they help readers understand where the journey is going.

### 1. Agent ownership model

Before building a real system, decide who owns each layer:

- The product team owns the user-facing behavior and escalation policy.
- The engineering team owns tool contracts, state, deployment, and observability.
- The security team owns identity, data boundaries, and approval policy.
- The operations team owns SLOs, alerts, and incident response.

An agent with no ownership model becomes hard to change safely.

### 2. Autonomy levels

Not every agent needs the same level of autonomy. A useful scale is:

- Assist: summarize, classify, draft.
- Recommend: suggest action, but do not execute.
- Act with approval: prepare side effects and request human confirmation.
- Act within policy: execute low-risk actions inside narrow permissions.
- Coordinate: route work across specialist agents.

Thain begins in the Assist stage. Later chapters move it gradually toward approved action and coordinated execution.

### 3. Evidence-first reasoning

Production agents should increasingly operate from evidence, not just fluent generation. This means every important answer should be traceable to one or more of:

- user input
- retrieved memory
- retrieved documents
- tool results
- policy decisions
- approval outcomes

Chapter 1 introduces the destination. Chapters 4, 6, 8, and 9 make the evidence trail concrete.

### 4. Platform portability

The chapter uses Microsoft Foundry because the book is Azure-focused. Architecturally, the first design question is broader: what should be platform-specific and what should remain application-owned?

Good candidates for application-owned code:

- business instructions
- tool contracts
- approval rules
- memory schemas
- routing decisions
- evaluation rubrics

Good candidates for platform services:

- model inference
- identity
- telemetry export
- managed storage
- managed search
- deployment and hosting

Keeping that boundary clear makes future framework and model upgrades easier.

## Reader extension ideas

- Write an "autonomy policy" for Thain before touching code: what can it do without approval, what requires approval, and what must never be automated?
- Create a one-page decision record for why Thain starts as a single agent instead of a multi-agent system.
- Define three production success metrics early: one quality metric, one latency metric, and one cost metric.

## References

- Microsoft Agent Framework documentation: https://learn.microsoft.com/en-ca/agent-framework/?view=agent-framework-python-latest
- Microsoft Foundry provider guidance for Agent Framework: https://learn.microsoft.com/en-us/agent-framework/agents/providers/microsoft-foundry
- OpenAI Agents SDK guide: https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK 2026 update: https://openai.com/index/the-next-evolution-of-the-agents-sdk/
- Anthropic, Building Effective AI Agents: https://resources.anthropic.com/building-effective-ai-agents

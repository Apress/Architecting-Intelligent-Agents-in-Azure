# Chapter 7 Architecture Notes

## Chapter anchor

Chapter 7 moves Thain from a single agent into a coordinated multi-agent system. The chapter introduces specialized roles for safety, triage, recall, knowledge, action, and orchestration. All outputs flow through a shared blackboard, and a central orchestrator owns routing and final response synthesis.

The chapter's core principle is deliberate collaboration. Agents do not chat freely with each other. They produce structured artifacts, and the orchestrator decides what happens next.

## Architectural lens

The most important architectural decision in Chapter 7 is centralized control with specialized execution.

Each agent gets a narrow responsibility. No specialist has full system authority. The orchestrator owns the turn lifecycle, routing, precedence, failure handling, and final user response.

This avoids a common multi-agent anti-pattern: letting agents negotiate through free-form messages until something plausible emerges. That style can be useful for experimentation, but it is difficult to audit and govern in production.

Thain's blackboard pattern gives collaboration a contract. Each participant writes its own result. The orchestrator merges those results according to defined rules.

## Current production trend: multi-agent systems are becoming workflow systems

As of May 2026, agent frameworks increasingly expose multi-agent orchestration as workflow patterns: sequential, concurrent, group chat, handoff, and graph-based execution. Microsoft Agent Framework documentation describes workflows as directed execution graphs, with orchestration patterns for strict sequencing, parallel execution, group collaboration, and handoffs.

The trend is useful, but it also creates a design choice. Just because a framework supports group chat does not mean every enterprise system should use open-ended group chat. For regulated workflows, deterministic sequencing and explicit state often matter more than conversational flexibility.

Thain's design is closer to a governed workflow than a casual agent swarm.

## Design implications for Thain

The safety gate runs early because safety constraints should shape all downstream behavior. Triage runs before retrieval and action because intent should determine which evidence and tools are relevant. Recall and knowledge are read-oriented enrichment steps. Action is last because side effects should happen only after evidence, policy, and approval have been considered.

That sequence is a production control plane:

1. Check safety.
2. Understand intent.
3. Gather evidence.
4. Decide whether action is allowed.
5. Synthesize one response.

The blackboard is also an audit surface. It records not only the final answer but the intermediate artifacts that led to it. That makes failure analysis possible when one specialist returns poor data or a downstream action is denied.

## Beyond the chapter

The chapter builds the core multi-agent architecture. The companion repo can point readers toward the next coordination concerns.

### 1. Agent contracts

Every specialist should have a stable input and output contract. If the recall agent changes its result shape, the orchestrator should fail clearly rather than silently misread it.

### 2. Routing tests

Multi-agent systems need routing tests. These tests should prove that the right agents run for known scenarios and that unsafe or denied paths halt correctly.

### 3. Parallelism with care

Some stages can run concurrently, but not all. Recall and knowledge may be parallel candidates after triage. Safety should usually stay first. Action should usually stay late.

### 4. Protocol boundaries

Protocols such as A2A can standardize communication between independent agents or external agent services. They do not replace the internal control plane. Thain's invariants should remain the same whether a specialist is local Python code, a hosted agent, or an A2A endpoint.

### 5. Human escalation

Human escalation should be a first-class outcome, not a generic failure. The safety and approval paths should be able to route to a human without pretending the system completed normally.

## Reader extension ideas

- Add contract tests for each blackboard result type.
- Add a routing matrix that maps scenarios to expected agent execution paths.
- Run recall and knowledge in parallel after triage and compare trace output.
- Add an explicit `human_escalation` result type to the blackboard.

## References

- Microsoft Agent Framework workflow overview: https://learn.microsoft.com/en-us/agent-framework/workflows/
- Microsoft Agent Framework sequential orchestration: https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/sequential
- Microsoft Agent Framework concurrent orchestration: https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/concurrent
- Microsoft Agent Framework group chat orchestration: https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/group-chat
- Agent2Agent protocol specification: https://a2aproject.github.io/A2A/latest/specification/

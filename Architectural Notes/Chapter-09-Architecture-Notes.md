# Chapter 9 Architecture Notes

## Chapter anchor

Chapter 9 makes Thain measurable. The system is already deployed, governed, observable, and approval-aware. This chapter adds durable human feedback, repeatable LLM-as-judge evaluation, and targeted policy hardening based on measured defects.

The chapter is careful about the word "learning." Thain does not silently retrain itself or rewrite its own behavior. It improves through an engineering loop: measure, diagnose, fix at the correct boundary, and re-measure.

## Architectural lens

The most important architectural decision in Chapter 9 is to keep improvement outside the live reasoning loop.

Feedback is captured as an auditable signal. Evaluations run against fixed datasets and rubrics. Defects are corrected in the appropriate layer, such as retrieval propagation or response policy, rather than by asking the model to "do better."

This protects the architectural invariants established in earlier chapters. Safety, approvals, orchestration, and traceability remain stable while quality improves.

## Current production trend: agent quality is becoming trace-based and rubric-driven

As of May 2026, agent evaluation is moving beyond single-response scoring. Microsoft Foundry evaluation supports LLM-as-judge metrics for quality, safety, tool use, and task behavior. OpenAI's evaluation tooling includes graders and trace grading, where full agent traces can be assessed across examples to identify regressions or validate improvements.

This trend matches Chapter 9 closely. Agents are not just text generators. They make tool calls, route work, retrieve evidence, and enforce policies. Evaluation must look at the whole run, not only the final answer.

## Design implications for Thain

The feedback API treats human judgment as data. Feedback is durable, queryable, and connected to telemetry. That means it can support review workflows and quality dashboards instead of disappearing into informal comments.

The evaluation framework adds repeatability. A fixed dataset and rubric let the team compare before-and-after behavior. This is critical because agent improvements can regress other scenarios.

The v1.12 hardening step shows the right correction style. The issue was not treated as a vague model failure. The system identified a boundary problem: retrieval worked, but synthesis did not use the evidence properly. The fix strengthened evidence propagation and response policy enforcement.

The protocol discussion in the chapter also matters. MCP and A2A can attach at boundaries, but they do not replace Thain's internal invariants. Tools, memory, safety, approvals, feedback, and evaluation remain explicit contracts.

## Beyond the chapter

The chapter introduces a mature improvement loop. The companion repo can point readers toward additional evaluation concerns.

### 1. Human feedback quality

Feedback data can be noisy. Reviewers may disagree, rating scales may drift, and comments may be incomplete. Production systems should track reviewer identity, rubric version, scenario, and confidence where appropriate.

### 2. Judge calibration

LLM-as-judge systems need calibration against human-reviewed examples. A judge that rewards the wrong behavior can push engineering effort in the wrong direction.

### 3. Regression suites

Every fix should run against prior scenarios. An improvement to retrieval synthesis should not weaken safety refusal, approval messaging, or tool-use accuracy.

### 4. Trace-level evals

Final-answer evals are not enough for agents. Trace-level evals can check whether the right tool was selected, whether the right evidence was used, whether policy fired, and whether the final answer matched recorded reality.

### 5. Protocol adoption

MCP and A2A are useful boundary protocols, but they expand the integration surface. Protocol adoption should include authentication, authorization, schema versioning, audit logging, and incident response.

## Reader extension ideas

- Add a small human-reviewed golden set for judge calibration.
- Add an eval that checks tool-selection accuracy, not only answer quality.
- Add rubric versioning to evaluation result records.
- Add a regression gate that blocks deployment if safety or approval scenarios degrade.

## References

- Microsoft Agent Framework evaluation: https://learn.microsoft.com/en-us/agent-framework/agents/evaluation
- Microsoft Foundry Agent Framework tracing and observability: https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-framework
- OpenAI graders guide: https://platform.openai.com/docs/guides/graders/
- OpenAI agent evals guide: https://platform.openai.com/docs/guides/agent-evals
- OpenAI trace grading guide: https://platform.openai.com/docs/guides/trace-grading
- Model Context Protocol specification: https://modelcontextprotocol.io/specification
- Agent2Agent protocol specification: https://a2aproject.github.io/A2A/latest/specification/

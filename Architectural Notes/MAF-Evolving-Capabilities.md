# MAF Evolving Capabilities

## Purpose

This companion note maps newer Microsoft Agent Framework capabilities to the book's chapter arc. The book focuses on building Thain as an architectural system: memory, retrieval, tools, governance, orchestration, deployment, feedback, evaluation, and scale.

MAF is evolving quickly. Some newer features are not covered directly in the chapters because they were still emerging, in preview, or would have shifted the book from an architecture journey into a framework catalogue. This note helps readers understand where those capabilities fit.

## What the book already covers

The book covers the core production architecture concerns that remain relevant even as framework APIs evolve:

1. Agent runtime and tools: Chapters 1-2
2. Short-term and persistent memory: Chapters 2-3
3. Semantic retrieval and grounding: Chapter 4
4. Agentic tools and approvals: Chapter 5
5. Observability, governance, audit, and failure handling: Chapter 6
6. Multi-agent orchestration with a blackboard control plane: Chapter 7
7. Production deployment and managed Azure services: Chapter 8
8. Feedback and evaluation: Chapter 9
9. Cost, performance, reliability, and scale readiness: Chapter 10

The newer MAF capabilities below should be seen as additional implementation options, not replacements for those architectural concerns.

## 1. MAF Workflows API

## Related chapters

Chapter 7 is the closest match. It builds Thain's multi-agent orchestration through a custom blackboard and orchestrator.

## What newer MAF adds

Current MAF includes workflow APIs for building explicit orchestration flows. These include functional workflows, graph workflows, executors, edges, conditional routing, parallel execution, workflow events, workflow-as-agent patterns, and typed message flow.

## How it maps to Thain

Thain's Chapter 7 control plane could be implemented with MAF workflows instead of custom orchestration classes. For example:

- Safety Gate -> Triage -> Recall / Knowledge -> Action -> Orchestrator could become a sequential workflow.
- Recall and Knowledge could become parallel branches after triage.
- Blackboard state could map to workflow state or typed messages.
- The final orchestrator could become the designated output node.

## Why the book uses custom orchestration

The book intentionally makes the control plane visible. Readers can see exactly how safety, routing, evidence, approvals, and final response synthesis interact. That is valuable before adopting a higher-level workflow abstraction.

## Suggested reader experiment

Rebuild Chapter 7 Part A as a MAF workflow with explicit executors and edges, then compare the trace output with the custom blackboard version.

## 2. Middleware

## Related chapters

Chapters 5 and 6 are the closest match. Chapter 5 introduces tools and approvals. Chapter 6 introduces tracing, policy enforcement, redaction, and failure handling.

## What newer MAF adds

MAF includes middleware for intercepting and modifying agent runs, function calls, and chat client calls. Middleware can handle cross-cutting concerns such as logging, security validation, error handling, request blocking, result transformation, and timing.

## How it maps to Thain

Chapter 6's `_wrap_tool()` pattern could be replaced or supplemented with function middleware. Some governance checks could move into agent middleware. Model-call timing or request decoration could move into chat middleware.

## Why the book uses explicit wrappers

The wrapper pattern makes the enforcement mechanics easy to read. It also keeps the trust layer mostly independent from MAF. That is useful for teaching and for portability.

In a production MAF-first implementation, middleware would be a strong candidate for the final shape of these cross-cutting concerns.

## Suggested reader experiment

Move Chapter 6 tool tracing from `_wrap_tool()` into function middleware and keep the same trace event schema.

## 3. Checkpointing, resume, and time-travel

## Related chapters

Chapters 5, 6, 8, and 9 are the closest matches. Chapter 5 introduces approvals, Chapter 6 introduces audit and trace replay, Chapter 8 adds durable approval workflows, and Chapter 9 adds measured improvement.

## What newer MAF adds

MAF workflow samples include checkpointing, checkpoint resume, human-in-the-loop resume, and Cosmos DB checkpoint storage. These features allow long-running workflows to pause, persist state, and continue later.

## How it maps to Thain

Chapter 8's asynchronous approval flow is conceptually close to checkpoint/resume. A write action can request approval, persist the pending state, and resume when a human decision arrives.

With MAF workflow checkpointing, parts of this could become framework-managed workflow state rather than custom approval-state plumbing.

## Why the book uses custom durable approvals

The book's implementation makes approval state explicit: approval IDs, status, expiry, execution marking, trace IDs, and audit records. That is the right concept to teach first. Framework checkpointing can reduce boilerplate later, but it does not remove the need to design approval semantics.

## Suggested reader experiment

Rebuild Chapter 8 Sprint 6's approval-gated action as a checkpointed workflow that pauses for human approval and resumes after the decision.

## 4. Built-in evaluation framework

## Related chapters

Chapter 9 is the closest match.

## What newer MAF adds

MAF includes built-in evaluation primitives such as `evaluate_agent()`, `evaluate_workflow()`, `EvalItem`, `LocalEvaluator`, and Foundry-backed evaluators. It also supports local checks such as keyword checks, tool-call checks, expected tool calls, expected outputs, and conversation split strategies.

## How it maps to Thain

Chapter 9's custom LLM-as-judge evaluation could be supplemented with MAF's built-in evaluation framework:

- Use local evaluators for smoke tests and CI gates.
- Use expected tool-call checks for agentic search and approval scenarios.
- Use Foundry evaluators for quality and safety metrics.
- Use workflow evaluation once Chapter 7 orchestration is expressed as a MAF workflow.

## Why the book uses custom evaluation

The custom evaluator teaches the evaluation architecture directly: fixed dataset, judge prompt, result storage, rubric, before/after comparison, and measured improvement. That remains valuable even if MAF provides convenience APIs.

## Suggested reader experiment

Port the Chapter 9 v1.11 eval set to `evaluate_agent()` and compare results with the custom judge script.

## 5. Foundry Hosted Agents

## Related chapters

Chapter 8 is the closest match.

## What newer MAF adds

Foundry Hosted Agents provide a managed hosting path for Agent Framework agents. Microsoft Foundry can handle managed infrastructure, session persistence, dedicated agent identity, lifecycle management, and OpenAI-compatible endpoints.

At the time of this companion update, Foundry Hosted Agents are still in preview. Treat them as an emerging deployment option rather than the default production baseline.

## How it maps to Thain

Chapter 8 deploys Thain to Azure Container Apps. A future version could explore Foundry Hosted Agents as an alternate hosting model for the same architecture.

The core concerns would not disappear:

- identity
- governance
- observability
- data boundaries
- approvals
- evaluation
- operational ownership
- cost and reliability

Hosted Agents may reduce hosting boilerplate, but they do not replace system design.

## Why the book uses Azure Container Apps

Azure Container Apps exposes the production architecture directly. Readers see the container boundary, managed identity, telemetry export, deployment validation, service dependencies, approval workflow, and operational hardening.

That is useful for a book about architecting production agentic systems.

## Suggested reader experiment

After completing Chapter 8, create a separate branch that hosts the final Thain agent through Foundry Hosted Agents and compare the operational responsibilities that move to the platform.

## 6. Declarative agents and declarative workflows

## Related chapters

Chapters 2 and 7 are the closest matches. Chapter 2 defines the first agent programmatically. Chapter 7 defines orchestration programmatically.

## What newer MAF adds

MAF supports declarative agents and declarative workflows using YAML or JSON. This lets teams define agent configuration, instructions, models, and workflow structure outside application code.

## How it maps to Thain

Thain's agent definitions, specialist roles, and multi-agent pipeline could be expressed declaratively. This may help teams version agent configuration separately from Python implementation.

## Why the book uses code-first definitions

The book teaches the mechanics of the system. Code-first implementation makes dependencies, state, policies, and failure paths explicit. Declarative configuration is easier to appreciate after readers understand what the configuration is controlling.

## Suggested reader experiment

Convert the Chapter 7 specialist agent definitions into declarative YAML while keeping the same blackboard contracts.

## 7. Agent Skills

## Related chapters

Chapters 4, 5, 8, and 9 are the closest matches.

## What newer MAF adds

Agent Skills are portable packages of instructions, scripts, and resources. They use progressive disclosure so agents see skill names and descriptions first, then load detailed instructions and resources only when needed.

## How it maps to Thain

Skills could package domain-specific support procedures, troubleshooting playbooks, escalation policies, refund rules, or diagnostic flows. This overlaps with Chapter 5 document retrieval and Chapter 8 production knowledge retrieval.

## Why the book uses retrieval and tools instead

The book builds retrieval, tools, and approvals from first principles. That helps readers understand evidence flow, source control, approval boundaries, and auditability.

Skills are useful once the team wants reusable domain capability packages.

## Suggested reader experiment

Create a `support-escalation` skill containing escalation rules and compare it with the Chapter 5 `retrieve_docs` tool.

## 8. MCP integration

## Related chapters

Chapters 5 and 9 are the closest matches. Chapter 5 introduces tools. Chapter 9 discusses protocol-resilient boundaries.

## What newer MAF adds

MAF samples include MCP integration. MCP standardizes how external tools, resources, and prompts can be exposed to agents.

## How it maps to Thain

Thain's retrieval, ticketing, notification, approval, or knowledge tools could be exposed through MCP servers. This would make those capabilities reusable by other agents or clients.

## Why the book does not implement MCP

The book focuses on the architecture inside Thain: tool contracts, approval rules, traceability, and policy enforcement. MCP changes how tools are exposed, but it does not remove the need for those controls.

## Suggested reader experiment

Expose `retrieve_docs` or `search_similar_complaints` through an MCP server and keep the same read/write governance model.

## 9. A2A hosting and agent-to-agent protocols

## Related chapters

Chapters 7, 8, and 9 are the closest matches.

## What newer MAF adds

MAF hosting samples include A2A patterns. A2A can standardize communication between agents or agent services across process and platform boundaries.

## How it maps to Thain

Thain's specialist agents could eventually become independently hosted agents that communicate through A2A. The orchestrator could call a recall agent, knowledge agent, or action agent over a protocol boundary rather than as local Python classes.

## Why the book keeps agents local

Local agents keep the core orchestration model visible. Distributed agents introduce network failures, authentication, protocol versioning, deployment ownership, and latency. Those are real production concerns, but they would distract from the core Chapter 7 control-plane design.

## Suggested reader experiment

Host the Knowledge Agent as a separate A2A-compatible service and keep the same blackboard result contract.

## 10. AgentSession, AgentThread, and framework-native conversation state

## Related chapters

Chapters 2 and 3 are the closest matches.

## What newer MAF adds

MAF samples now use framework-native session or thread concepts for multi-turn conversations. These can preserve conversation state across agent runs and support cleaner handoff between runtime and memory layers.

## How it maps to Thain

Chapter 2's in-memory buffer and Chapter 3's persistent memory service could be supplemented with framework-native session handling. The application would still need durable domain memory for complaint records, but conversation state could be more runtime-native.

## Why the book uses explicit memory layers

The book distinguishes conversational memory from domain memory. That distinction is important. A transcript is not the same thing as a normalized complaint record.

## Suggested reader experiment

Replace Chapter 2's interactive loop memory with an `AgentSession`, then keep Chapter 3's Cosmos-backed complaint memory as domain memory.

## 11. Streaming and background responses

## Related chapters

Chapters 2, 8, and 10 are the closest matches.

## What newer MAF adds

MAF samples include response streaming and background response patterns. Streaming can improve perceived latency, and background responses can support long-running work.

## How it maps to Thain

Thain's CLI and API paths could stream the final triage response. Long-running approval or retrieval workflows could use background response patterns where appropriate.

## Why the book keeps responses simple

The book prioritizes architecture clarity. Streaming adds client behavior, partial output handling, cancellation, and telemetry complexity. Those concerns are useful later, but they are not necessary for the core architecture.

## Suggested reader experiment

Add streaming to the Chapter 8 API while preserving trace IDs and final structured telemetry.

## 12. Provider flexibility

## Related chapters

Chapters 1, 2, 8, and 10 are the closest matches.

## What newer MAF adds

MAF supports multiple providers across Microsoft Foundry, Azure OpenAI, OpenAI, Anthropic, Ollama, Bedrock, Copilot Studio, GitHub Copilot, and others. The framework is designed to let provider choices evolve.

## How it maps to Thain

Thain is intentionally Azure-first. A provider abstraction could make model selection, local testing, fallback, or evaluation routing more flexible.

## Why the book stays Azure-first

The book is about architecting intelligent agents in Azure. Keeping the provider path focused lets the book go deeper on Azure identity, Cosmos DB, Azure AI Search, Application Insights, Content Safety, and deployment.

## Suggested reader experiment

Create a provider adapter that can switch between Foundry and OpenAI clients while preserving the same agent, tools, and tests.

## 13. Multimodal input

## Related chapters

This is not central to the current book. It could connect to Chapters 4 and 5 if support tickets include screenshots, documents, or media.

## What newer MAF adds

MAF samples include multimodal input patterns.

## How it maps to Thain

Future versions of Thain could analyze screenshots of device issues, uploaded PDFs, or support images. That would require new safety, storage, retrieval, and privacy rules.

## Why the book excludes it

The book's domain is text-heavy customer feedback. Adding multimodal input would expand the scope significantly.

## Suggested reader experiment

Add screenshot intake as a separate read-only diagnostic path, with explicit content safety and storage policy.

## 14. Framework-provided search and memory providers

## Related chapters

Chapters 3 and 4 are the closest matches.

## What newer MAF adds

The MAF ecosystem includes provider surfaces for memory, search, and Foundry embeddings. These can reduce the amount of custom code required for common scenarios.

## How it maps to Thain

Chapter 3's Cosmos repository and Chapter 4's Azure AI Search service could eventually be replaced or supplemented with framework-provided providers.

## Why the book builds these manually

Manual implementation teaches partitioning, TTL, schema design, retrieval scoring, context injection, and graceful degradation. Those are the architectural ideas readers need even when using a packaged provider.

## Suggested reader experiment

Replace `SemanticContextProvider` with a framework-provided search/context provider and compare the behavior, tests, and traceability.

## Recommended final note for readers

These newer MAF capabilities are useful, but they do not invalidate the book's architecture. They mostly provide higher-level ways to implement ideas the book already teaches:

- Workflows can implement the Chapter 7 control plane.
- Middleware can implement parts of Chapter 6 governance and tracing.
- Checkpointing can strengthen Chapter 8 approvals.
- Built-in evals can supplement Chapter 9's evaluation loop.
- Hosted Agents can offer a future alternative to Chapter 8 hosting.
- Skills, MCP, and A2A can package or expose capabilities at system boundaries.

The durable lesson is this: framework features reduce boilerplate, but production architecture still requires clear contracts, explicit state, governance boundaries, observability, evaluation, and failure handling.

## References

The GitHub repository and samples are the safest starting point because they track the current framework surface directly. The Microsoft Learn links below were checked while preparing this note; if any documentation page moves, use the GitHub samples as the fallback reference.

- Microsoft Agent Framework GitHub repository: https://github.com/microsoft/agent-framework
- Microsoft Agent Framework Python samples: https://github.com/microsoft/agent-framework/tree/main/python/samples
- Python workflow samples: https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows
- Python hosting samples: https://github.com/microsoft/agent-framework/tree/main/python/samples/04-hosting
- Python end-to-end samples: https://github.com/microsoft/agent-framework/tree/main/python/samples/05-end-to-end
- Microsoft Agent Framework workflows overview: https://learn.microsoft.com/en-us/agent-framework/workflows/
- Microsoft Agent Framework middleware: https://learn.microsoft.com/en-us/agent-framework/agents/middleware/
- Microsoft Agent Framework evaluation: https://learn.microsoft.com/en-us/agent-framework/agents/evaluation
- Microsoft Foundry provider guidance: https://learn.microsoft.com/en-us/agent-framework/agents/providers/microsoft-foundry
- Foundry Hosted Agents: https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent
- Declarative agents: https://learn.microsoft.com/en-us/agent-framework/agents/declarative
- Declarative workflows: https://learn.microsoft.com/en-us/agent-framework/workflows/declarative
- Agent Skills: https://learn.microsoft.com/en-us/agent-framework/agents/skills

# Chapter 10 Architecture Notes

## Chapter anchor

Chapter 10 turns Thain into an enterprise-grade service. The system is already production-ready and measurable. This chapter adds cost and latency telemetry, response compaction, model profile observability, caching, bounded retries, timeout budgets, cooldown suppression, chaos validation, and SLO alerting.

The chapter defines scale carefully. Scale is not only high throughput. For Thain, scale means operational readiness: cost control, predictable latency, dependency resilience, and controlled failure behavior.

## Architectural lens

The most important architectural decision in Chapter 10 is to optimize without changing the system's reasoning semantics.

The orchestration model remains stable. Safety, approval, retrieval, and evaluation boundaries remain intact. Optimization is layered around the runtime through telemetry, compaction, caching, model profiling, and reliability policies.

That is the right production rule: preserve architectural invariants while improving efficiency.

## Current production trend: optimization starts with measurement

As of May 2026, cost and latency guidance across model platforms emphasizes the same sequence: measure first, reduce unnecessary requests and tokens, select the right model for the task, use caching where possible, and validate quality after each optimization.

OpenAI's current cost guidance calls out request reduction, token minimization, smaller model selection, batch processing, and flex processing. Prompt caching guidance emphasizes stable prompt prefixes and monitoring cached token counts. Azure Well-Architected guidance applies the same broader principles: balance cost, reliability, performance, security, and operational excellence.

Chapter 10 follows that sequence. Sprint 2.1 measures. Sprint 2.2 optimizes. Sprint 2.3 hardens failure behavior.

## Design implications for Thain

Sprint 2.1 adds request-level cost, token, and latency telemetry. Even when SDK token metadata is unavailable, the runtime records whether usage came from the SDK or from a heuristic estimate. That transparency matters because teams should know which numbers are precise and which are directional.

Sprint 2.2 adds response compaction, in-memory caching, and model profile tagging. These are useful only because Chapter 9 already created an evaluation loop. Performance changes should be checked against quality regressions.

Sprint 2.3 adds a centralized reliability executor. This is the right layer for timeout, retry, and cooldown policy because it avoids scattering resilience logic across every service wrapper. It also makes dependency behavior observable.

The three-plane architecture at the end of the chapter is the mature version of the book's design. Data acquisition, knowledge preparation, and agent execution have different scale, cost, and failure profiles. Separating them keeps the runtime focused and protects the agent from ingestion and indexing failures.

## Beyond the chapter

The chapter establishes a strong v2.0 baseline. The companion repo can point readers toward additional scale concerns.

### 1. SLO ownership

An SLO is only useful if someone owns it. Define who responds when latency, fallback rate, retrieval failure rate, approval backlog, or cost per request crosses a threshold.

### 2. Cache correctness

Caching can reduce cost and latency, but it can also serve stale or incorrectly scoped information. Caches need keys, TTLs, invalidation rules, and tenant boundaries.

### 3. Model routing

Model profiles are the start of model routing. A mature system may route low-risk classification, synthesis, evaluation, and escalation tasks to different models. Every routing change should be evaluated for quality and safety.

### 4. Chaos scenarios

Reliability is not proven by code inspection. It is proven by controlled failure drills. Search outage, Cosmos latency, OpenAI timeout, content safety failure, and approval workflow failure should each have expected degraded behavior.

### 5. Cost as a product signal

Cost should be visible per scenario, tenant, model profile, and feature path. Expensive paths may be justified, but they should be intentional.

## Reader extension ideas

- Add SLO definitions for latency, fallback rate, and cost per request.
- Add cache hit/miss dashboards split by scenario.
- Add eval gates for each model profile.
- Add chaos validation for approval workflow failure.
- Add a monthly cost report grouped by feature path.

## References

- OpenAI cost optimization guide: https://platform.openai.com/docs/guides/cost-optimization
- OpenAI prompt caching guide: https://platform.openai.com/docs/guides/prompt-caching
- OpenAI latency optimization guide: https://platform.openai.com/docs/guides/latency-optimization
- Azure Well-Architected Framework: https://learn.microsoft.com/en-us/azure/well-architected/
- Azure AI workload design principles: https://learn.microsoft.com/en-us/azure/well-architected/ai/design-principles
- Azure reliability tradeoffs: https://learn.microsoft.com/en-us/azure/well-architected/reliability/tradeoffs

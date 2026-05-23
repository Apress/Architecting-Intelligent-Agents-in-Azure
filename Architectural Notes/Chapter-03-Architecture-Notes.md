# Chapter 3 Architecture Notes

## Chapter anchor

Chapter 3 gives Thain durable memory. The agent moves from remembering only within a running process to recalling complaint history across sessions through Azure Cosmos DB.

The GA companion code introduces a persistent data model, an async Cosmos repository, a memory service, a `PersistentContextProvider`, TTL-aware storage, and a small TTL-aware cache for recent reads. Together, these pieces turn memory into an external system of record rather than a local list.

## Architectural lens

The most important architectural decision in Chapter 3 is to treat memory as a managed subsystem, not as chat history dumped into a database.

For an agent, memory has three separate responsibilities:

1. Write: decide what should be stored.
2. Manage: expire, summarize, correct, partition, and protect stored records.
3. Read: retrieve the right memories at the right time and inject them into context.

Chapter 3 implements the first production-shaped version of that loop. The write path stores normalized complaint records. The read path fetches recent records through `PersistentContextProvider`. The manage path begins with TTL and a bounded cache.

The central question is no longer "can the agent remember?" The better question is "which memories should influence the next decision?"

## Current production trend: memory is becoming first-class infrastructure

As of May 2026, production agent memory has moved beyond append-only vector stores. Current platform guidance and research increasingly describe memory as a governed write-manage-read loop with filtering, retrieval, expiry, partitioning, privacy, and evaluation.

Microsoft's Azure Cosmos DB agent memory guidance distinguishes short-term memory from long-term memory, discusses partition-key tradeoffs, and recommends one document per turn as a practical storage unit for many agent applications. It also highlights that full-text and vector search can be combined for different recall needs.

Recent memory research points in the same direction. The hard problems are not only storage and retrieval. They include contradiction handling, latency budgets, privacy governance, learned forgetting, and multi-session evaluation.

That fits Thain's progression well. Chapter 2 adds short-term memory. Chapter 3 adds durable memory. Chapter 4 adds semantic recall. Later chapters add governance, evaluation, and operational controls.

## Design implications for Thain

The Chapter 3 repository partitions by `/customerId`. That is a good teaching choice because it keeps a customer's complaints colocated and makes recent-history queries efficient.

In larger systems, the partition key becomes a governance and cost decision. A single customer key is simple. A tenant key helps isolate enterprise customers. Hierarchical keys such as tenant/user/thread can improve locality and reduce cross-partition fan-out. A GUID-style key distributes writes well but can make recall queries more expensive.

TTL is another important design signal. The code supports configurable expiry through `COSMOS_TTL_DAYS`. That is not just cleanup. Agent memory can contain sensitive customer data, so retention policy is part of the system's governance model.

The `PersistentContextProvider` is the chapter's most reusable pattern. It fetches recent records before the model run and appends them as context. That keeps durable recall separate from the agent's core orchestration. A future production refactor could use the GA `after_run` hook for write-back, letting the provider own both sides of the memory lifecycle.

The small LRU cache also matters. `PersistentMemoryService.persist` clears the cache after writes, which prevents recent-memory reads from staying stale. In production, cache correctness affects answer quality as much as retrieval correctness.

## Beyond the chapter

The book keeps Chapter 3 focused on Cosmos-backed persistence. The companion repo can point readers toward the production memory concerns that follow.

### 1. Memory write filtering

Not every turn should become long-term memory. A production memory service usually needs a write policy:

- store only useful facts or decisions
- skip low-value chatter
- redact secrets and sensitive fields
- attach source and confidence metadata
- distinguish raw records from summaries

Thain stores normalized complaint records, which is appropriate for the chapter. A real deployment should formalize what is allowed into memory.

### 2. Memory correction and forgetting

Persistent memory can be wrong. Customers may correct themselves, agents may summarize poorly, and policies may change.

Production memory needs a way to mark records as superseded, delete records, correct summaries, preserve audit history where required, and stop stale memory from overriding newer evidence. TTL handles expiry, but it does not handle contradiction.

### 3. Hybrid retrieval

Chapter 3 retrieves recent customer records. Chapter 4 adds semantic search. Modern memory systems often combine several retrieval paths:

- recent-turn retrieval
- exact filters
- BM25 or full-text search
- vector search
- reranking
- summarization

Cosmos DB now supports both full-text and vector-oriented memory patterns, while Azure AI Search remains a strong dedicated retrieval service. The right split depends on scale, ranking needs, tenant isolation, and operational ownership.

### 4. Partitioning for future scale

The current `/customerId` partition is readable and useful for a chapter example. For a multi-tenant SaaS deployment, a hierarchy such as `/tenantId`, `/userId`, and `/threadId` may be more appropriate.

Microsoft's vector search performance guidance recommends scoping searches to partition keys where possible because cross-partition searches are more expensive. That lesson applies before vector search is added: memory layout should follow access patterns.

### 5. Memory evaluation

Testing memory is harder than testing a CRUD repository. Useful memory tests ask:

- did the system recall the right prior complaint?
- did it ignore irrelevant memories?
- did memory improve the answer?
- did stale memory harm the answer?
- did tenant isolation hold?
- did TTL remove expired records?

Chapter 9 later introduces evaluation. For memory-heavy agents, some of that thinking should start much earlier.

## Reader extension ideas

- Move persistent write-back into `PersistentContextProvider.after_run` and keep `main.py` focused on orchestration.
- Add a memory write policy that redacts or skips sensitive fields before storage.
- Add tenant-isolation tests so one customer's records never appear in another customer's context.
- Add a `source_version` field to `ComplaintRecordModel` for future schema migrations.
- Add cache hit/miss logging to `PersistentMemoryService`.

## References

- Azure Cosmos DB agent memory guidance: https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/agentic-memories
- Azure Cosmos DB vector indexing and search performance guidance: https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/vector-search-performance-tips
- Microsoft Foundry provider guidance for Agent Framework: https://learn.microsoft.com/en-us/agent-framework/agents/providers/microsoft-foundry
- Microsoft Agent Framework context provider API reference: https://learn.microsoft.com/en-us/python/api/azure-ai-agentserver-agentframework/azure.ai.agentserver.agentframework.foundrytoolscontextprovider?view=azure-python-preview
- Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers: https://arxiv.org/abs/2603.07670

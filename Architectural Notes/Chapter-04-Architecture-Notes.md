# Chapter 4 Architecture Notes

## Chapter anchor

Chapter 4 moves Thain beyond user-scoped memory. Cosmos DB gives Thain continuity for a known customer, but real support patterns often repeat across many users with different wording. This chapter adds semantic retrieval with Azure AI Search and embeddings so Thain can connect related complaints by meaning.

The chapter also improves the user-facing output from raw JSON to a Markdown triage card. That is not only a presentation change. It makes the agent's reasoning easier for people to inspect, compare, and hand off.

## Architectural lens

The most important architectural decision in Chapter 4 is to treat retrieval as evidence injection, not as hidden prompt enrichment.

Thain does not ask the model to remember everything. It builds a retrieval layer that embeds the current complaint, searches historical records, and injects the most relevant matches through a `SemanticContextProvider`. This keeps retrieval separate from reasoning while still grounding the model in prior evidence.

That separation matters in production. Retrieval can be tested, tuned, and monitored independently from the model. The agent can improve its answers without giving the model unlimited access to every record.

## Current production trend: hybrid retrieval is becoming the default RAG shape

As of May 2026, production RAG systems increasingly combine vector search with lexical search, filters, semantic ranking, and reranking. Azure AI Search hybrid search runs full-text and vector queries together and merges results with Reciprocal Rank Fusion. This reflects a broader trend: vector search is powerful, but it is not the entire retrieval system.

For agentic systems, the retrieval layer also needs operational controls:

- metadata filters for tenant, customer, category, and recency
- source labels for grounding and audit
- top-k limits to control token cost
- retrieval quality tests
- graceful fallback when search or embeddings fail

Chapter 4 introduces the foundation. Later chapters turn retrieval into an explicit tool, production-backed knowledge service, and evaluated evidence pipeline.

## Design implications for Thain

Persistent memory and semantic recall serve different purposes.

Persistent memory answers: what has this customer recently told us?

Semantic recall answers: what related issues has the wider system seen before?

Those two memory types should remain distinct. User-scoped memory supports continuity and personalization. Semantic recall supports pattern recognition and operational insight. Mixing them carelessly can leak information across customers or allow unrelated records to distort the answer.

The `SemanticContextProvider` is the right boundary because it lets the agent runtime pull semantic evidence only when a turn is being prepared. Retrieval remains testable and replaceable. If Azure AI Search, Cosmos DB vector search, or a managed retrieval service is used later, the agent contract does not need to change.

The triage card also matters. A useful agent output should expose the result, the insight, and the suggested next step. That gives operators a lightweight audit surface even before full tracing arrives in Chapter 6.

## Beyond the chapter

The book keeps Chapter 4 focused on building semantic retrieval from the ground up. The companion repo can point readers toward the retrieval concerns that show up in production.

### 1. Retrieval quality evaluation

A retrieval system should be tested separately from the final answer. Useful checks include:

- did the expected historical complaint appear in top-k?
- did irrelevant complaints stay out?
- did filters enforce customer or tenant boundaries?
- did the retrieved context improve the answer?
- did stale evidence harm the answer?

These checks become especially important when changing embedding models, chunking rules, or index schema.

### 2. Hybrid search and reranking

Pure vector search can miss exact terms, product IDs, ticket numbers, and policy names. Pure keyword search can miss paraphrases. Hybrid search combines both. For production support systems, hybrid retrieval plus semantic ranking is often a stronger default than vector-only retrieval.

### 3. Provenance and citation

The chapter injects related complaints as context. A production version should preserve source metadata all the way to the final answer and trace:

- record ID
- customer or tenant scope
- timestamp
- score
- retrieval method
- index version

The user-facing answer does not always need to show all of this, but the audit trail should.

### 4. Index lifecycle

Search indexes are production assets. They need versioning, backfills, validation, and rollback strategy. Changing an embedding model or index schema can silently change agent behavior.

### 5. Managed retrieval services

Managed retrieval and grounding services can reduce custom code, but they do not remove the architecture questions. Teams still need to understand isolation, source quality, cost, latency, and failure behavior.

## Reader extension ideas

- Add a retrieval evaluation file with expected queries and expected complaint IDs.
- Add score and source metadata to the context injected by `SemanticContextProvider`.
- Try a hybrid retrieval path that combines keyword and vector search.
- Add a retrieval fallback message when embeddings or search are unavailable.

## References

- Azure AI Search hybrid search overview: https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
- Azure AI Search hybrid query guide: https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query
- Azure AI Search vector search overview: https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- Azure Cosmos DB agent memory guidance: https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/agentic-memories
- Microsoft Foundry provider guidance for Agent Framework: https://learn.microsoft.com/en-us/agent-framework/agents/providers/microsoft-foundry

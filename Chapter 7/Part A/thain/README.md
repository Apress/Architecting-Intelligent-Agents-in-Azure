# Thain Support Triage Agent — Chapter 7 Part A: Blackboard Orchestration

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use `Code GA/Chapter 7/Part A/thain`.

Part A introduces multi-agent collaboration via the Blackboard pattern. A coordinator agent writes a shared workspace entry; specialist sub-agents read from it and contribute their results back. Thain learns to delegate rather than reason alone.

## Prerequisites

- Python 3.11+
- An Azure OpenAI resource with a GPT-4o deployment
- Azure Cosmos DB account (NoSQL API)
- Azure AI Search resource with a semantic search index
- An Azure OpenAI embeddings deployment

## Configuration

Fill in the `.env` file included in this folder with your Azure resource details:

```
AZURE_AI_PROJECT_ENDPOINT=https://<project>.cognitiveservices.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<model-deployment-name>

COSMOS_ENDPOINT=https://<cosmos-account>.documents.azure.com:443/
COSMOS_KEY=<key-or-leave-blank-for-managed-identity>
COSMOS_DATABASE=<database-name>
COSMOS_CONTAINER=<container-name>

AZURE_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
AZURE_SEARCH_INDEX_NAME=<index-name>
AZURE_OPENAI_EMBEDDING_ENDPOINT=https://<openai-resource>.openai.azure.com
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<embedding-deployment-name>

ENABLE_TICKETS=false
ENABLE_NOTIFICATIONS=false
ENABLE_DOCS=false
ENABLE_WRITE_APPROVALS=false

TRACE_OUTPUT_DIR=traces

# Triage routing: deterministic | llm
TRIAGE_MODE=deterministic
```

Authenticate with Azure AD: `az login`

## Usage

```bash
python main.py --message "My device keeps overheating and shutting down."
```

```bash
python main.py --interactive
```

```bash
python main.py --devui --devui-open
```

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/
```

## Key Learnings

- ✅ Implement the Blackboard pattern for shared agent state.
- ✅ Coordinate multiple specialist agents from a single orchestrator.
- ✅ Route complaints deterministically or via LLM-based triage.

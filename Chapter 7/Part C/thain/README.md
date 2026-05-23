# Thain Support Triage Agent — Chapter 7 Part C: Full Collaboration

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use `Code GA/Chapter 7/Part C/thain`.

Part C completes the multi-agent system. An ActionAgent joins the blackboard, capable of creating tickets and sending notifications. The orchestrator now coordinates three specialist agents — triage, recall, and action — in a governed, observable pipeline.

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
TRIAGE_MODE=deterministic
```

Authenticate with Azure AD: `az login`

## Usage

```bash
python main.py --message "Screen cracked on first drop. Please raise a warranty ticket."
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

- ✅ Orchestrate three specialist agents (triage, recall, action) via the blackboard.
- ✅ Apply governance and audit to all agents in the collaboration.
- ✅ Gate action agent write operations behind the approval interceptor.
- ✅ Compose a full multi-agent pipeline with shared state and trust controls.

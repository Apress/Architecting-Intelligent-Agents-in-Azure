# Thain Support Triage Agent — Chapter 7 Part B: Recall Agent

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 7 Part B code.

Part B adds a dedicated RecallAgent that performs semantic search over past incidents and posts its findings to the blackboard. The orchestrator now has both a triage signal and a history-aware recall signal before deciding on a response.

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
python main.py --message "Battery swelling again — same as last month."
```

```bash
python main.py --interactive
```

```bash
python main.py --devui --devui-open
```

## Running Tests

```bash
pip install -r requirements.txt -c constraints.txt
pytest tests/
```

## Key Learnings

- ✅ Build a dedicated RecallAgent that posts semantic search results to the blackboard.
- ✅ Combine triage and recall signals before formulating a response.
- ✅ Tune recency and relevance thresholds for semantic recall.

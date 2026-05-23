# Thain Support Triage Agent — Chapter 6 Part A: Observability

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use `Code GA/Chapter 6/Part A/thain`.

Part A introduces structured observability. Every agent run emits OpenTelemetry spans to Application Insights, and JSON trace files are written locally, giving you full visibility into reasoning steps, tool calls, and latency.

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

# Trace files are written here (default: traces/)
TRACE_OUTPUT_DIR=traces
```

Authenticate with Azure AD: `az login`

## Usage

```bash
python main.py --message "My invoice shows a charge I did not authorise."
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

- ✅ Emit OpenTelemetry spans from agent runs to Application Insights.
- ✅ Write structured JSON trace files for local inspection.
- ✅ Observe reasoning steps, tool calls, and token usage per run.

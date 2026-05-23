# Thain Support Triage Agent — Chapter 6 Part C: Trust (Full)

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 6 Part C code.

Part C completes the trust layer. An immutable audit trail records every policy decision and tool call outcome. Thain now earns trust through transparency: every action is observable, governed, and auditable.

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
```

Authenticate with Azure AD: `az login`

## Usage

```bash
python main.py --message "Why was my ticket closed without resolution?"
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

- ✅ Append immutable audit records for every policy decision and tool outcome.
- ✅ Compose observability, governance, and audit into a layered trust pipeline.
- ✅ Query the audit trail to reconstruct the full decision history for any run.

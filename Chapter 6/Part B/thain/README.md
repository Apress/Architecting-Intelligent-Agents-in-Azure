# Thain Support Triage Agent — Chapter 6 Part B: Governance

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use `Code GA/Chapter 6/Part B/thain`.

Part B adds a Policy Decision Point (PDP). Every tool call is evaluated against a governance policy before execution — tools that fail the policy check are denied and the reason is surfaced to the caller.

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
python main.py --message "Please create a ticket for my broken screen."
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

- ✅ Implement a Policy Decision Point (PDP) as a tool interceptor.
- ✅ Evaluate tool calls against a configurable governance policy.
- ✅ Return structured deny responses with reasons.
- ✅ Combine governance and observability in a single pipeline.

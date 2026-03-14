# Thain Support Triage Agent — Chapter 4: Thain Connects the Dots

Thain gains long-term semantic memory. Complaint history is stored in Cosmos DB and retrieved via Azure AI Search using vector embeddings, so Thain can recognise recurring issues and surface relevant past incidents alongside each new complaint.

## Prerequisites

- Python 3.11+
- An Azure OpenAI resource with a GPT-4o deployment
- Azure Cosmos DB account (NoSQL API)
- Azure AI Search resource with a semantic search index
- An Azure OpenAI embeddings deployment (e.g. `text-embedding-ada-002`)

## Configuration

Fill in the `.env` file included in this folder with your Azure resource details:

```
AZURE_AI_PROJECT_ENDPOINT=https://<project>.cognitiveservices.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<model-deployment-name>

COSMOS_ENDPOINT=https://<cosmos-account>.documents.azure.com:443/
COSMOS_KEY=<key-or-leave-blank-for-managed-identity>
COSMOS_DATABASE=<database-name>
COSMOS_CONTAINER=<container-name>
COSMOS_TTL_DAYS=30
THAIN_CUSTOMER_ID=thain-demo

AZURE_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
AZURE_SEARCH_INDEX_NAME=<index-name>
AZURE_SEARCH_API_KEY=<key-or-leave-blank-for-managed-identity>
AZURE_OPENAI_EMBEDDING_ENDPOINT=https://<openai-resource>.openai.azure.com
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<embedding-deployment-name>
AZURE_OPENAI_EMBEDDING_API_KEY=<key-or-leave-blank-for-managed-identity>
```

Cosmos DB and Azure AI Search are optional — Thain degrades gracefully if they are unavailable.
Authenticate with Azure AD: `az login`

## Usage

### Single message (CLI)

```bash
python main.py --message "The screen flickers every time I open a browser tab."
```

### Interactive REPL

```bash
python main.py --interactive
```

### DevUI (web console)

```bash
python main.py --devui --devui-open
```

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/
```

## Key Learnings

- ✅ Persist complaint history to Cosmos DB with configurable TTL.
- ✅ Retrieve semantically similar past incidents using Azure AI Search.
- ✅ Feed recalled context into the agent via a `ContextProvider`.
- ✅ Gracefully degrade when external services are unavailable.
- ✅ Configure vector embeddings for semantic similarity search.

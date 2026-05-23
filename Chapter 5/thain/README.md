# Thain Support Triage Agent — Chapter 5: Thain Builds Its Toolkit

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use `Code GA/Chapter 5/thain`.

Thain gains a full set of write-capable action tools: ticket creation, customer notifications, and knowledge-base documentation. An approval interceptor gates write operations so human sign-off is required before any action takes effect.

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
COSMOS_TTL_DAYS=30
THAIN_CUSTOMER_ID=thain-demo

AZURE_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
AZURE_SEARCH_INDEX_NAME=<index-name>
AZURE_SEARCH_API_KEY=<key-or-leave-blank-for-managed-identity>
AZURE_OPENAI_EMBEDDING_ENDPOINT=https://<openai-resource>.openai.azure.com
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<embedding-deployment-name>
AZURE_OPENAI_EMBEDDING_API_KEY=<key-or-leave-blank-for-managed-identity>

# Set to true to enable each write capability
ENABLE_TICKETS=false
ENABLE_NOTIFICATIONS=false
ENABLE_DOCS=false
ENABLE_WRITE_APPROVALS=false
```

Authenticate with Azure AD: `az login`

## Usage

### Single message (CLI)

```bash
python main.py --message "This is the third time my charger has failed."
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

- ✅ Register multiple action tools using `@ai_function`.
- ✅ Gate write operations behind a configurable approval interceptor.
- ✅ Toggle capabilities at runtime using environment flags.
- ✅ Handle approval denial gracefully and surface the reason to the caller.
- ✅ Compose read and write tools in a single agent reasoning loop.

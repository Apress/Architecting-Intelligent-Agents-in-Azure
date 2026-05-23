# Thain Support Triage Agent

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 9 v1.1 code.

Thain listens to a single customer complaint, reasons over it with Azure OpenAI GPT-4o via the Microsoft Agent Framework (MAF), optionally calls a keyword classifier, and prints a structured Markdown triage card.

## Prerequisites

- Python 3.11+
- An Azure OpenAI resource with an **Assistants**-enabled GPT-4o deployment
- GA packages: `agent-framework==1.5.0`, `agent-framework-core==1.5.0`, `agent-framework-foundry==1.5.0` (installed via `pip install -r requirements.txt -c constraints.txt`)

## Configuration

Create or update a local `.env` file (not committed) with:

```
AZURE_AI_PROJECT_ENDPOINT=https://<project>.cognitiveservices.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<model-deployment-name>
COSMOS_ENDPOINT=https://<cosmos-account>.documents.azure.com:443/
COSMOS_KEY=<cosmos-key-or-empty-when-using-msi>
COSMOS_DATABASE=<database-name>
COSMOS_CONTAINER=<container-name>
COSMOS_TTL_DAYS=30
THAIN_CUSTOMER_ID=thain-demo
# Agentic action flags
ENABLE_TICKETS=true
ENABLE_NOTIFICATIONS=true
ENABLE_DOCS=true
ENABLE_WRITE_APPROVALS=true
```

The app loads this file automatically via `python-dotenv`.  
Authenticate with Azure AD by running `az login` so `DefaultAzureCredential` can obtain a token.

> **Write-approvals note:** When `ENABLE_WRITE_APPROVALS=true`, tools that mutate state (ticket creation, notifications) require an in-flight approval record. For local CLI or unit-test runs without a full approval store, set `ENABLE_WRITE_APPROVALS=false` to bypass the approval gate.

## Usage

### Single message (CLI)

```bash
python main.py --message "The phone battery started swelling again after the last update."
```

Or pipe text from stdin:

```bash
echo "Wi-Fi keeps dropping whenever I move between rooms." | python main.py
```

On success, the script prints a Markdown triage card such as:

```
**Triage Summary for Complaint ID #C-20260519A1B2**
---
**Issue Type**
Connectivity Issue
---
**Summary**
Customer reports recurring Wi-Fi dropouts when moving between rooms.
---
**Insight**
Similar pattern seen in complaint #C-20260312X7Y3 regarding intermittent connectivity after firmware update.
---
**Suggest**
Escalate to network team; check router firmware version and recent OTA update logs.
```

### Interactive REPL

```bash
python main.py --interactive
```

Enter complaints one at a time; Thain keeps short-term memory for the duration of the session. Use `quit` or `exit` to leave.

### DevUI (web console)

```bash
python main.py --devui --devui-open
```

Enable OpenTelemetry export when debugging with:

```bash
python main.py --devui --devui-tracing
```

This launches the Microsoft Agent Framework DevUI at `http://127.0.0.1:8080`. Adjust the host or port with `--devui-host` / `--devui-port`. Include `--devui-open` to auto-open the browser.

## Implementation Notes

- The script builds an Agent Framework `Agent` backed by `FoundryChatClient` and registers the keyword classifier via the `@tool` decorator (`classify_issue_tool`).
- Short-term context is provided by an in-memory `MemoryContextProvider`; long-term context comes from a Cosmos DB-backed `PersistentContextProvider`.
- Semantic recall uses Azure AI Search plus Azure OpenAI embeddings so Thain can cite similar complaints even when phrasing differs.
- The agent is instructed to produce a structured Markdown triage card (not JSON). The keyword classifier runs if the model omits a category.

## Persistent Memory

- Cosmos DB stores durable complaint records. Set `COSMOS_TTL_DAYS` to control how long memories stay fresh (default 30 days).
- Retrieval returns the most recent complaints for the configured customer and gracefully degrades if Cosmos DB is unavailable.

## Semantic Recall

- Azure AI Search + Azure OpenAI embeddings power semantic recall (enable via the `AZURE_SEARCH_*` and `AZURE_OPENAI_EMBEDDING_*` settings).
- Thain queries the vector index for similar complaints and surfaces short references inside the prompt so it can relate new issues to past trends.
- Toggle the feature or adjust how many neighbors are returned via `AZURE_SEARCH_MODE` and `AZURE_SEARCH_TOP_K`.

## Key Learnings

- ? Initialize and configure the Microsoft Agent Framework (GA 1.5.0) for Python.
- ? Use async execution to run agents efficiently.
- ? Register a tool using the GA `@tool` decorator.
- ? Store and reuse short-term context with a memory provider.
- ? Run Thain in both single-message and interactive modes.
- ? Use the DevUI to observe reasoning, tool calls, and traces in real time.
- ? Read structured Markdown triage cards produced by an LLM for downstream use.


## Observability

Tracing and redaction helpers live in `observability/`. This folder contains the trace recorder, ID helpers, and the file-based trace sink used for Part A.

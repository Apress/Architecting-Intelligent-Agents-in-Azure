# Thain Support Triage Agent

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use Code GA/Chapter 9/v1.1/thain.

Thain listens to a single customer complaint, reasons over it with Azure OpenAI GPT-4o via the Microsoft Agent Framework (MAF), optionally calls a keyword classifier, and returns a concise JSON response containing an inferred issue category and summary.

## Prerequisites

- Python 3.11+
- An Azure OpenAI resource with an **Assistants**-enabled GPT-4o deployment
- The chapter beta dependencies from `requirements.txt` and `constraints.txt` (install with `pip install -r requirements.txt -c constraints.txt`)

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
```

The app loads this file automatically via `python-dotenv`.  
Authenticate with Azure AD by running `az login` so `DefaultAzureCredential` can obtain a token.

## Usage

### Single message (CLI)

```bash
python main.py --message "The phone battery started swelling again after the last update."
```

Or pipe text from stdin:

```bash
echo "Wi-Fi keeps dropping whenever I move between rooms." | python main.py
```

On success, the script prints a JSON object such as:

```json
{"category": "Connectivity Issue", "summary": "Customer reports recurring Wi-Fi dropouts when moving around the house."}
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

- The script builds an Agent Framework `ChatAgent` backed by `AzureAIAgentClient` and registers the keyword classifier via the `@ai_function` decorator (`classify_issue_tool`).
- Short-term context is provided by an in-memory `MemoryContextProvider`; long-term context comes from a Cosmos DB-backed `PersistentContextProvider`.
- Semantic recall uses Azure AI Search plus Azure OpenAI embeddings so Thain can cite similar complaints even when phrasing differs.
- Note: The agent may choose its own category wording (e.g., “Connectivity” vs “Connectivity Issue”). The keyword classifier only steps in if the model omits a category or the JSON needs repair.
- The agent is instructed to emit valid JSON and will fall back to the classifier result if it omits a category.

## Persistent Memory

- Cosmos DB stores durable complaint records. Set `COSMOS_TTL_DAYS` to control how long memories stay fresh (default 30 days).
- Retrieval returns the most recent complaints for the configured customer and gracefully degrades if Cosmos DB is unavailable.

## Semantic Recall

- Azure AI Search + Azure OpenAI embeddings power semantic recall (enable via the `AZURE_SEARCH_*` and `AZURE_OPENAI_EMBEDDING_*` settings).
- Thain queries the vector index for similar complaints and surfaces short references inside the prompt so it can relate new issues to past trends.
- Toggle the feature or adjust how many neighbors are returned via `AZURE_SEARCH_MODE` and `AZURE_SEARCH_TOP_K`.

## Key Learnings

- ✅ Initialize and configure the Microsoft Agent Framework for Python.
- ✅ Use async execution to run agents efficiently.
- ✅ Register a tool using the native `@ai_function` decorator.
- ✅ Store and reuse short-term context with a memory provider.
- ✅ Run Thain in both single-message and interactive modes.
- ✅ Use the DevUI to observe reasoning, tool calls, and traces in real time.
- ✅ Parse structured JSON responses from an LLM for downstream use.


## Observability

Tracing and redaction helpers live in `observability/`. This folder contains the trace recorder, ID helpers, and the file-based trace sink used for Part A.

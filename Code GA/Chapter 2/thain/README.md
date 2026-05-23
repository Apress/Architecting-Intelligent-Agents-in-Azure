# Thain Support Triage Agent

Thain listens to a single customer complaint, reasons over it with Azure OpenAI GPT-4o via the Microsoft Agent Framework (MAF), optionally calls a lightweight keyword classifier, and returns a concise JSON response containing an inferred issue category and summary.

## Prerequisites

- Python 3.11+
- An Azure AI Foundry project with a GPT-4o deployment
- Python packages installed from `requirements.txt` (includes `agent-framework` and `agent-framework-foundry`)

## Configuration

Fill in the `.env` file included in this folder with your Azure resource details:

```
AZURE_AI_PROJECT_ENDPOINT=https://<project>.cognitiveservices.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<model-deployment-name>
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

- The script builds an Agent Framework `Agent` backed by `FoundryChatClient` and registers the keyword classifier via the `@tool` decorator (`classify_issue_tool`).
- A `MemoryContextProvider` surfaces recent complaints through the `before_run` context provider hook so the agent receives short-term history without manual prompt stitching.
- The agent is instructed to emit valid JSON and will fall back to the classifier result if it omits a category.

## Key Learnings

- ✅ Initialize and configure the Microsoft Agent Framework for Python.
- ✅ Use async execution to run agents efficiently.
- ✅ Register a tool using the native `@tool` decorator.
- ✅ Store and reuse short-term context with a memory provider.
- ✅ Run Thain in both single-message and interactive modes.
- ✅ Use the DevUI to observe reasoning, tool calls, and traces in real time.
- ✅ Parse structured JSON responses from an LLM for downstream use.

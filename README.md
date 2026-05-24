# Architecting Intelligent Agents in Azure

Source code for [*Architecting Intelligent Agents in Azure: Building Agentic Systems with Python and the Microsoft Agent Framework*](https://link.springer.com/book/9798868824326) by Hari Narayn (Apress, 2026).

[comment]: #cover
![Cover image](9798868824326.jpg)

## Start Here

The book follows a single agent, **Thain**, a support triage agent, across ten chapters. Each chapter evolves the same agentic system forward, introducing new architectural capabilities while preserving prior behavior.

This repository focuses on production-grade agentic system architecture: reasoning, memory, retrieval, governance, observability, evaluation, and operational reliability.

| Folder | What it contains |
|--------|-----------------|
| `Chapter X/` | Original code matching the printed book listings |
| `Code GA/Chapter X/` | Runnable MAF 1.5.0 GA implementation of the same system |
| `Migration Notes/` | Chapter-by-chapter API change reference (beta to GA) |
| `Architectural Notes/` | Design decisions and modern MAF capability mapping |

The original `Chapter X/` listings preserve the structure and flow of the printed manuscript. See `Code GA/README.md` for setup instructions.

## Chapter Map

| Chapter | Title | Key Concepts |
|---------|-------|-------------|
| 1 | Thain: The Beginning | Azure AI Foundry setup, agent concepts (no runnable code, Foundry walkthrough) |
| 2 | Thain Meets the Agent Framework | MAF basics, reasoning loop, tools |
| 3 | Thain Learns to Remember | Cosmos DB persistence, memory tiers |
| 4 | Thain Connects the Dots | Semantic recall, Azure AI Search, RAG |
| 5 | Thain Builds Its Toolkit | Custom tools, approval workflows |
| 6 | Thain Earns Trust | Governance, observability, content safety |
| 7 | Thain Learns to Collaborate | Multi-agent, blackboard orchestration |
| 8 | Thain Goes Live | FastAPI, Docker, Azure Container Apps, IaC |
| 9 | Thain Learns from Us | Feedback loops, LLM-as-judge evaluation |
| 10 | Thain at Scale | Streaming, cost optimisation, reliability |

## Running the Code

**GA code (Chapters 2 to 10):**

```bash
cd "Code GA/Chapter {N}/thain"
python -m venv .venv
.\.venv\Scripts\activate        # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt -c constraints.txt
```

**Original book listings (Chapters 2 to 10):**

The `Chapter {N}/` folders match the printed listings and support the MAF DevUI for interactive exploration of agent reasoning, tool calls, and traces:

```bash
cd "Chapter {N}/thain"
python -m venv .venv
.\.venv\Scripts\activate        # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt -c constraints.txt
python main.py --devui --devui-open
```

Create your own `.env` file with the required Azure settings before running. Authenticate with `az login` or `az login --use-device-code` if needed.

## Contributions

See `Contributing.md` for more information on how you can contribute to this repository.

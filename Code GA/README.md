# Code GA - Microsoft Agent Framework 1.5.0 Companion Code

This folder contains the Microsoft Agent Framework 1.5.0 General Availability (GA) version of the companion code for *Architecting Intelligent Agents in Azure: Building Agentic Systems with Python and the Microsoft Agent Framework*.

The printed listings preserve the book's architectural learning path. The `Code GA/` tree provides the current runnable implementation, with the same system architecture migrated to `agent-framework==1.5.0` and `agent-framework-foundry==1.5.0`.

## Repository Structure

From the repository root:

```
Chapter X/            - original code matching the book listings
Code GA/Chapter X/    - GA 1.5.0 migrated code with passing tests
Migration Notes/      - chapter-by-chapter migration reference
Architectural Notes/  - chapter-level architecture notes and modern capability mapping
```

Each chapter folder is self-contained and independently testable. Migration notes explain API changes and any GA-companion improvements made along the way. Architectural notes explain production design choices and point to framework-native paths readers can explore after completing the book implementation.

---

## Setting Up a Fresh Environment

Each chapter is a standalone project. The recommended approach is one virtual environment shared across all GA chapters, using the packages pinned in each chapter's `requirements.txt` and `constraints.txt`.

### Create and activate the venv

**Windows (PowerShell):**

```powershell
python -m venv maf-ga-env
.\maf-ga-env\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv maf-ga-env
source maf-ga-env/bin/activate
```

### Install dependencies for a chapter

Navigate to the chapter folder from the repository root and install with constraints pinned:

```bash
cd "Code GA/Chapter 4/thain"
pip install -r requirements.txt -c constraints.txt
```

The `constraints.txt` pins the exact GA package versions:

```text
agent-framework==1.5.0
agent-framework-core==1.5.0
agent-framework-foundry==1.5.0
agent-framework-devui==1.0.0b260519
```

> **Note:** `agent-framework-devui` remains on a beta release. DevUI is used in the book as a learning aid; it is not required to run or validate examples. Use the CLI or `pytest tests/` as the primary validation path.

### Validate a chapter

```bash
python -m pytest tests/ -v
```

### Run a single message via CLI

```bash
python main.py --message "The screen flickers every time I open a browser tab."
```

---

## Environment Files

Sanitized `.env` and `.env.dev` templates are included where chapters need them. Replace placeholder or blank values with your own Azure resource values before running deployed examples. Do not commit real keys, endpoints, tenant IDs, subscription IDs, or connection strings.

---

## Python Version

Python 3.11 or later is required. The GA packages are tested against Python 3.11.

---

## Migration Notes

Chapter-by-chapter migration references are in the `Migration Notes/` folder at the repo root. Each file covers:

- Package changes from the printed listings to GA
- API changes with before/after code snippets
- Test changes
- GA-companion improvements such as bug fixes and CLI output corrections

---

## Architectural Notes and MAF Evolving Capabilities

Microsoft Agent Framework is evolving quickly. The repo includes chapter-level files in `Architectural Notes/` and a companion note, `MAF-Evolving-Capabilities.md`, that maps newer framework features such as workflows, middleware, checkpointing, built-in evaluation, hosted agents, skills, MCP, and A2A to each chapter's architecture. These notes explain why the book builds core concerns explicitly and suggest experiments for readers who want to explore framework-native paths.

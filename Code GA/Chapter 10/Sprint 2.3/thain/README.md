# Chapter 10 — Sprint 2.3: Data and Reliability Hardening

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 10 Sprint 2.3 code.

This folder contains the Thain v2.0 codebase at the end of Sprint 2.3, introducing centralized reliability enforcement with bounded retries, timeout budgets, cooldown suppression, chaos validation, and Azure Monitor SLO alerting.

## What's new in this sprint

- `services/reliability.py` — centralized ReliabilityExecutor with per-dependency timeout, retry, and cooldown policies
- `main.py` — OpenAI calls wrapped under reliability executor with deterministic degraded fallback
- `services/embedding.py` — embedding calls wrapped under reliability executor
- `memory/repositories.py`, `services/approval_store.py` — Cosmos DB operations wrapped
- `memory/docs_search_client.py`, `memory/search_client.py` — Search operations wrapped
- `observability/trace_sinks.py` — root span projection for reliability telemetry fields
- `governance/logging_policy.py` — allowlist extended for reliability and fallback fields
- `infra/s2.3-01-configure-reliability.ps1` — writes reliability and chaos controls to `.env.dev`
- `infra/s2.3-02-provision-reliability-alerts.ps1` — provisions Azure Monitor alert rules
- `infra/s2.3-03-validate-reliability.ps1` — chaos scenario validation (normal, openai, cosmos, search)

## Setup

```bash
python -m venv .venv && .\.venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
```

Fill in `.env` with your Azure resource values. If running locally without a full approval store, set `ENABLE_WRITE_APPROVALS=false` in `.env` to bypass the approval gate (see write-approvals note below). Then configure and deploy:

```powershell
.\infra\s2.3-01-configure-reliability.ps1
.\infra\s1-02-build-push.ps1
.\infra\s1-03-deploy-app.ps1
.\infra\s2.3-02-provision-reliability-alerts.ps1
.\infra\s2.3-03-validate-reliability.ps1 -Scenario normal
```

To run a chaos scenario (e.g. OpenAI failure):

```powershell
.\infra\s2.3-01-configure-reliability.ps1 -ChaosOpenAIFailure
.\infra\s1-03-deploy-app.ps1
.\infra\s2.3-03-validate-reliability.ps1 -Scenario openai
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Write-approvals note

When `ENABLE_WRITE_APPROVALS=true`, tools that mutate state (ticket creation, notifications) require an in-flight approval record. Direct `import main` or CLI runs without a configured approval store will raise `MissingConfigError`. For local CLI or unit-test style runs, set `ENABLE_WRITE_APPROVALS=false` to bypass the approval gate.

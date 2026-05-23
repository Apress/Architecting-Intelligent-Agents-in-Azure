# Chapter 10 — Sprint 2.1: Instrument and Dashboard

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 10 Sprint 2.1 code.

This folder contains the Thain codebase at the end of Sprint 2.1, introducing request-level token, cost, and latency telemetry with an Application Insights operational dashboard.

## What's new in this sprint

- `main.py` — token usage extraction, cost estimation, structured `llm.usage` telemetry event
- `observability/trace_sinks.py` — root span projection for cost and latency fields
- `governance/logging_policy.py` — allowlist updated to include `llm.usage` fields
- `infra/s2.1-01-sync-openai-pricing.ps1` — pricing synchronisation from Azure Retail Prices API
- `infra/s2.1-02-validate-telemetry.ps1` — automated telemetry validation
- `infra/s2.1-03-provision-telemetry-workbook.ps1` — Application Insights workbook provisioning

## Setup

```bash
python -m venv .venv && .\.venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
```

Fill in `.env` with your Azure resource values. If running locally without a full approval store, set `ENABLE_WRITE_APPROVALS=false` in `.env` to bypass the approval gate (see write-approvals note below). Then run the pricing sync script before deploying:

```powershell
.\infra\s2.1-01-sync-openai-pricing.ps1
.\infra\s1-02-build-push.ps1
.\infra\s1-03-deploy-app.ps1
.\infra\s2.1-02-validate-telemetry.ps1
.\infra\s2.1-03-provision-telemetry-workbook.ps1
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Write-approvals note

When `ENABLE_WRITE_APPROVALS=true`, tools that mutate state (ticket creation, notifications) require an in-flight approval record. Direct `import main` or CLI runs without a configured approval store will raise `MissingConfigError`. For local CLI or unit-test style runs, set `ENABLE_WRITE_APPROVALS=false` to bypass the approval gate.

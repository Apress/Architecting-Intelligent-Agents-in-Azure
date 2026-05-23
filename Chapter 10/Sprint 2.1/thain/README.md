# Chapter 10 — Sprint 2.1: Instrument and Dashboard

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use Code GA/Chapter 10/Sprint 2.1/thain.

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

Fill in `.env` with your Azure resource values, then run the pricing sync script before deploying:

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

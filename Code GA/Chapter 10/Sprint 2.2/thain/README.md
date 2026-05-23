# Chapter 10 — Sprint 2.2: Performance Optimisation

This folder contains the Microsoft Agent Framework 1.5.0 GA version of the Chapter 10 Sprint 2.2 code.

This folder contains the Thain codebase at the end of Sprint 2.2, introducing governed runtime optimisation through response compaction, in-memory caching, and model profile observability.

## What's new in this sprint

- `main.py` — response compaction, bounded in-memory cache with TTL, model profile tagging
- `observability/trace_sinks.py` — root span projection for `thain.model.profile` and `thain.cache.hit`
- `governance/logging_policy.py` — allowlist extended for optimisation telemetry fields
- `infra/s2.2-01-configure-optimization.ps1` — writes optimisation controls to `.env.dev`
- `infra/s2.2-02-validate-optimization.ps1` — validation gate including LLM-as-judge regression check

## Setup

```bash
python -m venv .venv && .\.venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
```

Fill in `.env` with your Azure resource values. If running locally without a full approval store, set `ENABLE_WRITE_APPROVALS=false` in `.env` to bypass the approval gate (see write-approvals note below). Then configure and deploy:

```powershell
.\infra\s2.2-01-configure-optimization.ps1
.\infra\s1-02-build-push.ps1
.\infra\s1-03-deploy-app.ps1
.\infra\s2.2-02-validate-optimization.ps1
.\infra\s2.1-03-provision-telemetry-workbook.ps1
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Write-approvals note

When `ENABLE_WRITE_APPROVALS=true`, tools that mutate state (ticket creation, notifications) require an in-flight approval record. Direct `import main` or CLI runs without a configured approval store will raise `MissingConfigError`. For local CLI or unit-test style runs, set `ENABLE_WRITE_APPROVALS=false` to bypass the approval gate.

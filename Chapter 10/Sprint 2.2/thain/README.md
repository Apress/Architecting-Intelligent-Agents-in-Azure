# Chapter 10 — Sprint 2.2: Performance Optimisation

This folder contains the original beta code matching the book listings. For the GA 1.5.0 version, use Code GA/Chapter 10/Sprint 2.2/thain.

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

Fill in `.env` with your Azure resource values, then configure and deploy:

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

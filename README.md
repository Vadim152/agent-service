# agent-service

`agent-service` is a FastAPI backend for the Sber IDE plugin.

## Architecture

```text
Sber IDE Plugin
  -> agent-service (FastAPI, /api/v1/*)
    -> LangGraph workflows
      -> LangChain tools + local stores (steps index, memory, learning)
```

## Core Flows

- `POST /steps/scan-steps`
  - Scans project sources and updates Cucumber step index.
- `GET /steps?projectRoot=...`
  - Reads indexed steps.
- `POST /jobs`
  - Starts jobs-first feature generation pipeline:
  - parse testcase -> find/match indexed steps -> build feature -> optional apply.
  - The jobs pipeline does not run step scan.
- `GET /jobs/{jobId}` / `GET /jobs/{jobId}/result` / `GET /jobs/{jobId}/events`
  - Job lifecycle and result retrieval.
- `POST /chat/sessions` and related `/chat/*`
  - Chat control-plane compatible API backed by local LangGraph runtime.
- `POST /memory/feedback`
  - Records project-level feedback to improve future step ranking.
- `POST /tools/find-steps`, `POST /tools/compose-autotest`, `POST /tools/explain-unmapped`
  - Skill/tool endpoints for step retrieval, autotest composition and unmatched analysis.

## Requirements

- Python `3.10+`

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
```

## Run

```powershell
agent-service
```

Alternative:

```powershell
$env:PYTHONPATH="src"
python -m app.main
```

## Health

```powershell
curl http://localhost:8000/health
```

## Main Config

- `AGENT_SERVICE_API_PREFIX` (default `/api/v1`)
- `AGENT_SERVICE_HOST` (default `0.0.0.0`)
- `AGENT_SERVICE_PORT` (default `8000`)
- `AGENT_SERVICE_STEPS_INDEX_DIR` (default `.agent/steps_index`)
- `AGENT_SERVICE_ARTIFACTS_DIR` (default `.agent/artifacts`)

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider tests/test_chat_api.py tests/test_jobs_api.py
```

# agent-service

`agent-service` is a FastAPI control plane for BDD/test automation and the IntelliJ-based plugin.

Current focus:
- chat-first workflow in plugin ToolWindow;
- job orchestration for feature generation;
- approval-gated tool execution;
- self-healing execution loop for long-running jobs.

## What is implemented

### Core backend
- `Job API` for async orchestration (`/api/v1/jobs/*`).
- `ExecutionSupervisor` with attempts, classification/remediation hooks, and incident artifacts.
- `Orchestrator` based on LangGraph for scan -> parse -> match -> build -> apply.
- Persistent artifacts in `.agent/job_artifacts`.

### Chat control plane (new)
- Chat sessions and message processing (`/api/v1/chat/*`).
- Agent loop with intent routing and tool calling.
- Confirm-before-write policy for mutating/external tools.
- Session + project memory abstraction persisted in `.agent/chat_memory`.

### IntelliJ plugin (new UX)
- ToolWindow is now chat-only UI.
- Quick command chips (`/scan-steps`, `/generate-test`, `/new-automation`, `/help`).
- Approval cards for risky tool calls.
- History polling and status rendering from backend chat session.

Legacy actions are still present for compatibility (`Scan`, `Generate Feature`, `Apply Feature`).

## High-level architecture

```text
IDE Plugin Chat UI
    -> /api/v1/chat/sessions
    -> /api/v1/chat/sessions/{id}/messages
    -> /api/v1/chat/sessions/{id}/history
    -> /api/v1/chat/sessions/{id}/tool-decisions
    -> /api/v1/chat/sessions/{id}/stream (SSE)

ChatAgentRuntime
    -> tool registry (read/write/external risk levels)
    -> approval gate for mutating calls
    -> Job API bridge for long-running generation

Job API + ExecutionSupervisor
    -> Orchestrator (LangGraph)
    -> StepIndexStore / EmbeddingsStore / ArtifactStore / RunStateStore
```

## Repository structure

- `src/app` - startup/config/logging.
- `src/api` - HTTP routes and schemas.
- `src/chat` - chat runtime, session state, memory, tool registry.
- `src/agents` - orchestration agents and LangGraph facade.
- `src/self_healing` - execution supervisor and remediation components.
- `src/infrastructure` - stores/adapters (step index, artifacts, run state, LLM).
- `ide-plugin` - IntelliJ plugin module.
- `tests` - backend tests.

## Run locally

### Backend

Windows PowerShell:

```powershell
cd C:\path\to\agent-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m app.main
```

Linux/macOS:

```bash
cd /path/to/agent-service
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m app.main
```

Health check:

```bash
curl http://localhost:8000/health
```

### Plugin

```bash
./ide-plugin/gradlew -p ide-plugin buildPlugin
```

Windows:

```powershell
.\ide-plugin\gradlew.bat -p ide-plugin buildPlugin
```

## Environment variables

Base prefix: `AGENT_SERVICE_`.

Key settings:
- `AGENT_SERVICE_API_PREFIX` (default `/api/v1`)
- `AGENT_SERVICE_HOST` (default `0.0.0.0`)
- `AGENT_SERVICE_PORT` (default `8000`)
- `AGENT_SERVICE_STEPS_INDEX_DIR` (default `.agent/steps_index`)
- `GIGACHAT_CLIENT_ID`
- `GIGACHAT_CLIENT_SECRET`
- `GIGACHAT_SCOPE` (default `GIGACHAT_API_PERS`)
- `GIGACHAT_AUTH_URL`
- `GIGACHAT_API_URL`
- `GIGACHAT_VERIFY_SSL` (default `false`)

## API overview

Base URL examples below assume `http://localhost:8000/api/v1`.

### Job API

Create job:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot":"/path/to/project",
    "testCaseText":"Given user opens page",
    "targetPath":"src/test/resources/features/generated.feature",
    "createFile":true,
    "overwriteExisting":false,
    "profile":"quick",
    "source":"ide-plugin"
  }'
```

Get status/result/events:

```bash
curl http://localhost:8000/api/v1/jobs/{jobId}
curl http://localhost:8000/api/v1/jobs/{jobId}/result
curl -N http://localhost:8000/api/v1/jobs/{jobId}/events
```

### Chat API (new)

Create/reuse chat session:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot":"/path/to/project",
    "source":"ide-plugin",
    "profile":"quick",
    "reuseExisting":true
  }'
```

Send user message:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions/{sessionId}/messages \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"/generate-test Given user logs in"}'
```

Read history:

```bash
curl http://localhost:8000/api/v1/chat/sessions/{sessionId}/history
```

Approve/reject tool call:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions/{sessionId}/tool-decisions \
  -H "Content-Type: application/json" \
  -d '{"toolCallId":"<id>","decision":"approve"}'
```

SSE stream:

```bash
curl -N http://localhost:8000/api/v1/chat/sessions/{sessionId}/stream
```

### Other endpoints (compat/debug)

- `POST /api/v1/steps/scan-steps`
- `GET /api/v1/steps/?projectRoot=...`
- `POST /api/v1/feature/generate-feature`
- `POST /api/v1/feature/apply-feature`
- `POST /api/v1/llm/test`

## Tooling policy in chat runtime

Default policy is **confirm-before-write**:
- read-only tools can run automatically;
- write/external tools require explicit approval;
- pending tool calls are returned in chat history and UI approval cards.

## Tests

Backend:

```bash
python -m pytest -p no:cacheprovider tests/test_jobs_api.py tests/test_chat_api.py
```

Plugin:

```bash
./ide-plugin/gradlew -p ide-plugin test --no-daemon
```

## Notes

- Chat runtime currently uses history polling in plugin; SSE endpoint is already available in backend.
- Job and chat stores are process-local (`RunStateStore` in-memory) plus file-backed memory/artifacts.
- For production multi-instance deployment, replace in-memory stores with shared persistence.

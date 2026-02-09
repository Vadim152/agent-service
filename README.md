# agent-service

`agent-service` is a FastAPI backend for the Sber IDE plugin, implemented as a controlled wrapper over OpenCode SDK.

## Architecture

```text
Sber IDE Plugin
  -> agent-service (FastAPI, public API /api/v1/*)
    -> opencode-wrapper (Node sidecar, local/internal API)
      -> OpenCode runtime
```

### Component responsibilities

- `ide-plugin`
  - chat UI
  - sends user messages
  - renders pending approvals
  - sends permission decisions
- `agent-service`
  - public API entry point for IDE
  - request validation and API contract
  - bridges chat/session operations to sidecar
- `opencode-wrapper`
  - starts OpenCode server via SDK
  - consumes OpenCode event stream
  - exposes a simplified internal API for Python

## Current API surface

### Public API (`/api/v1`)

- Chat:
  - `POST /chat/sessions`
  - `POST /chat/sessions/{sessionId}/messages`
  - `GET /chat/sessions/{sessionId}/history`
  - `POST /chat/sessions/{sessionId}/tool-decisions`
  - `GET /chat/sessions/{sessionId}/stream`
- Compatibility/debug:
  - `POST /steps/scan-steps`
  - `GET /steps/?projectRoot=...`
  - `POST /feature/generate-feature`
  - `POST /feature/apply-feature`
  - `POST /llm/test`

### Internal sidecar API (`opencode-wrapper`, localhost only)

- `GET /internal/health`
- `POST /internal/sessions`
- `POST /internal/sessions/{id}/prompt-async`
- `POST /internal/sessions/{id}/permissions/{permissionId}`
- `GET /internal/sessions/{id}/history`
- `GET /internal/sessions/{id}/events` (SSE)

## Quick start

## 1) Requirements

- Python 3.10+
- Node.js 20+
- `opencode` CLI available in `PATH`

## 2) Install dependencies

Backend:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
```

Sidecar:

```powershell
cd opencode-wrapper
npm install
cd ..
```

## 3) Run services

Start sidecar first:

```powershell
cd opencode-wrapper
npm start
```

Start backend second:

```powershell
cd C:\Users\BaguM\IdeaProjects\agent-service
python -m app.main
```

Health checks:

```powershell
curl http://localhost:8000/health
curl http://127.0.0.1:8011/internal/health
```

## Configuration

Backend env prefix: `AGENT_SERVICE_`.

Key backend settings:

- `AGENT_SERVICE_API_PREFIX` (default: `/api/v1`)
- `AGENT_SERVICE_HOST` (default: `0.0.0.0`)
- `AGENT_SERVICE_PORT` (default: `8000`)
- `AGENT_SERVICE_STEPS_INDEX_DIR` (default: `.agent/steps_index`)
- `AGENT_SERVICE_OPENCODE_WRAPPER_URL` (default: `http://127.0.0.1:8011`)
- `AGENT_SERVICE_OPENCODE_TIMEOUT_S` (default: `30.0`)

Sidecar settings:

- `OPENCODE_WRAPPER_HOST` (default: `127.0.0.1`)
- `OPENCODE_WRAPPER_PORT` (default: `8011`)
- `OPENCODE_HOST` (default: `127.0.0.1`)
- `OPENCODE_PORT` (default: `4096`)
- `OPENCODE_STARTUP_TIMEOUT_MS` (default: `15000`)

## Chat API examples

Base URL: `http://localhost:8000/api/v1`.

Create or reuse session:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot": "C:/path/to/project",
    "source": "ide-plugin",
    "profile": "quick",
    "reuseExisting": true
  }'
```

Send user message:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions/{sessionId}/messages \
  -H "Content-Type: application/json" \
  -d '{
    "role": "user",
    "content": "Generate an automation plan for login flow"
  }'
```

Get history:

```bash
curl http://localhost:8000/api/v1/chat/sessions/{sessionId}/history
```

Reply to permission:

```bash
curl -X POST http://localhost:8000/api/v1/chat/sessions/{sessionId}/tool-decisions \
  -H "Content-Type: application/json" \
  -d '{
    "permissionId": "perm-123",
    "decision": "approve_once"
  }'
```

Allowed `decision` values:

- `approve_once`
- `approve_always`
- `reject`

SSE stream:

```bash
curl -N http://localhost:8000/api/v1/chat/sessions/{sessionId}/stream
```

## Plugin

Build plugin:

```powershell
./ide-plugin/gradlew -p ide-plugin buildPlugin
```

Notes:

- ToolWindow is chat-first.
- Approval cards use `pendingPermissions`.

## Tests

Backend:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider tests/test_chat_api.py tests/test_startup_readiness.py
python -m pytest -p no:cacheprovider tests/test_jobs_api.py
```

Plugin compile check:

```powershell
./ide-plugin/gradlew -p ide-plugin compileKotlin --no-daemon
```

## Current limitations

- Sidecar stores session events/pending permissions in process memory.
- Production deployment needs durable persistence and stream replay strategy.
- Jobs router is no longer included in the default public API router.

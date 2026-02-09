# agent-service

`agent-service` is a FastAPI backend for the Sber IDE plugin.  
It uses `opencode-wrapper` as a local control layer over OpenCode SDK/runtime.

## Architecture

```text
Sber IDE Plugin
  -> agent-service (FastAPI, public API: /api/v1/*)
    -> opencode-wrapper (Node.js sidecar, internal API: /internal/*)
      -> OpenCode SDK
        -> OpenCode runtime
```

## What Is Implemented

- Controlled sidecar wrapper (`opencode-wrapper`) around OpenCode SDK.
- Session control-plane API in backend:
  - current activity/state,
  - usage/cost data,
  - diff and risk summary,
  - control commands.
- Plugin UI focused on 3 operator questions:
  - what the agent is doing now,
  - how many resources it consumes,
  - what it is going to change.
- Approval flow with explicit decisions:
  - `approve_once`,
  - `approve_always`,
  - `reject`.

## Public API (`/api/v1`)

Base: `http://localhost:8000/api/v1`

### Chat session lifecycle

- `POST /chat/sessions`
- `POST /chat/sessions/{sessionId}/messages`
- `GET /chat/sessions/{sessionId}/history`
- `POST /chat/sessions/{sessionId}/tool-decisions`
- `GET /chat/sessions/{sessionId}/stream` (SSE)

Default plugin behavior: each new ToolWindow chat uses a fresh session (`reuseExisting=false`) to avoid old-history spam.

### Control-plane endpoints

- `GET /chat/sessions/{sessionId}/status`
- `GET /chat/sessions/{sessionId}/diff`
- `POST /chat/sessions/{sessionId}/commands`

`status` also includes retry diagnostics when provider is rate-limited:

- `lastRetryMessage`
- `lastRetryAttempt`
- `lastRetryAt`

`commands.command` supports:

- `status`
- `diff`
- `compact`
- `abort`
- `help`

### Other existing endpoints

- `POST /steps/scan-steps`
- `GET /steps?projectRoot=...`
- `POST /feature/generate-feature`
- `POST /feature/apply-feature`
- `POST /llm/test`

## Internal Sidecar API (`opencode-wrapper`)

Base: `http://127.0.0.1:8011/internal`

- `GET /health`
- `POST /sessions`
- `POST /sessions/{id}/prompt-async`
- `POST /sessions/{id}/permissions/{permissionId}`
- `GET /sessions/{id}/history`
- `GET /sessions/{id}/status`
- `GET /sessions/{id}/diff`
- `POST /sessions/{id}/commands`
- `GET /sessions/{id}/events` (SSE)

## Plugin UI Notes

ToolWindow includes:

- `Now` card:
  - activity,
  - current action,
  - pending approvals.
- `Cost and Usage` card:
  - token totals,
  - estimated cost,
  - context usage limits.
- `Planned Changes` card:
  - diff summary (files/additions/deletions),
  - risk level and reasons,
  - changed files list.

Quick command shortcuts in UI:

- `/status`
- `/diff`
- `/compact`
- `/abort`
- `/help`

Timeline rendering guards:

- empty assistant messages are hidden
- consecutive duplicate assistant messages are collapsed

## Quick Start

### 1. Requirements

- Python `3.10+`
- Node.js `20+`
- OpenCode CLI available (`opencode` or `opencode.cmd` on Windows)

### 2. Install

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

### 3. Run

Start sidecar:

```powershell
cd opencode-wrapper
npm start
```

Start backend (option A, preferred after `pip install -e .`):

```powershell
agent-service
```

Start backend (option B):

```powershell
$env:PYTHONPATH="src"
python -m app.main
```

### 4. Health checks

```powershell
curl http://localhost:8000/health
curl http://127.0.0.1:8011/internal/health
```

### 5. Stop services (Windows)

Stop `opencode-wrapper` and backend if they run in current terminal:

- Press `Ctrl+C` in each terminal.

If OpenCode runtime is left running on `127.0.0.1:4096`, stop it explicitly:

```powershell
# Find process listening on port 4096
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 4096 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess

# Stop that process (replace PID)
Stop-Process -Id <PID> -Force
```

## Configuration

### Backend (`AGENT_SERVICE_*`)

- `AGENT_SERVICE_API_PREFIX` (default `/api/v1`)
- `AGENT_SERVICE_HOST` (default `0.0.0.0`)
- `AGENT_SERVICE_PORT` (default `8000`)
- `AGENT_SERVICE_STEPS_INDEX_DIR` (default `.agent/steps_index`)
- `AGENT_SERVICE_OPENCODE_WRAPPER_URL` (default `http://127.0.0.1:8011`)
- `AGENT_SERVICE_OPENCODE_TIMEOUT_S` (default `30.0`)

### Sidecar (`OPENCODE_*`)

- `OPENCODE_WRAPPER_HOST` (default `127.0.0.1`)
- `OPENCODE_WRAPPER_PORT` (default `8011`)
- `OPENCODE_HOST` (default `127.0.0.1`)
- `OPENCODE_PORT` (default `4096`)
- `OPENCODE_STARTUP_TIMEOUT_MS` (default `15000`)
- `OPENCODE_BIN` (optional custom path to OpenCode binary)

## Smoke Example

```bash
# 1) create session
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"projectRoot":"C:/path/to/project","source":"ide-plugin","profile":"quick","reuseExisting":false}'

# 2) read status
curl http://localhost:8000/api/v1/chat/sessions/{sessionId}/status

# 3) read diff
curl http://localhost:8000/api/v1/chat/sessions/{sessionId}/diff

# 4) execute command
curl -X POST http://localhost:8000/api/v1/chat/sessions/{sessionId}/commands \
  -H "Content-Type: application/json" \
  -d '{"command":"compact"}'
```

## Verification

Backend tests:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src'
python -m pytest -p no:cacheprovider tests/test_chat_api.py tests/test_startup_readiness.py
python -m pytest -p no:cacheprovider tests/test_jobs_api.py
```

Plugin compile check:

```powershell
./ide-plugin/gradlew -p ide-plugin compileKotlin --no-daemon
```

## Current Limitations

- Sidecar state (events, pending permissions, usage aggregates) is in-memory.
- No durable event replay yet after sidecar restart.
- For production, persistence + recovery strategy should be added.

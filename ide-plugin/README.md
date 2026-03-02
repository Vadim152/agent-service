# ide-plugin

`ide-plugin` is an IntelliJ Platform plugin that works with the `agent-service` backend.

## Current Scope

- Tool window for chat with the agent
- Session/run control-plane integration through `/sessions/*`, `/runs/*`, and `/policy/*`
- Step scanning and feature generation/apply flows through `/platform/*`
- Runs-first feature generation with preserved chat UX

## Registered IDE Integration

According to `src/main/resources/META-INF/plugin.xml`, the plugin currently registers:

- Tool window `Агентум`
- Project settings page `Tools -> Агентум`
- Notification group `Агентум`

## Backend Integration

`HttpBackendClient` talks to:

- `POST /platform/steps/scan-steps`
- `GET /platform/steps`
- `POST /platform/feature/generate-feature`
- `POST /platform/feature/apply-feature`
- `POST /platform/tools/find-steps`
- `POST /platform/tools/compose-autotest`
- `POST /platform/tools/explain-unmapped`
- `GET|POST|PATCH|DELETE /platform/memory/*`
- `POST /runs`
- `GET /runs/{runId}`
- `GET /runs/{runId}/result`
- `GET /runs/{runId}/artifacts`
- `GET /runs/{runId}/events`
- `POST /sessions`
- `GET /sessions`
- `POST /sessions/{sessionId}/messages`
- `GET /sessions/{sessionId}/history`
- `GET /sessions/{sessionId}/status`
- `GET /sessions/{sessionId}/diff`
- `POST /sessions/{sessionId}/commands`
- `GET /sessions/{sessionId}/stream`
- `POST /policy/approvals/{approvalId}/decision`

## Main Flows

### Chat in the tool window

1. The plugin creates or reuses a session via `POST /sessions`
2. It sends messages through `POST /sessions/{sessionId}/messages`
3. It updates the UI through `/sessions/{sessionId}/stream` plus history/status refresh
4. Approval actions are sent to `/policy/approvals/{approvalId}/decision`

### Step scanning

1. The user sets `projectRoot` in settings
2. The plugin calls `POST /platform/steps/scan-steps`
3. It loads and displays the step index in the UI

### Feature generation

`GenerateFeatureFromSelectionAction` uses the runs-first flow:

1. `POST /runs` with `plugin=testgen`
2. Wait for a terminal state via `/runs/{id}/events` with polling fallback
3. Load the result from `GET /runs/{id}/result`
4. Open the generated feature and highlight unmapped steps

### Feature apply

`ApplyFeatureAction` calls `POST /platform/feature/apply-feature` and displays the resulting status.

## Build and Test

Requirements:

- JDK 17
- IntelliJ target `2025.1`

Commands:

```powershell
.\gradlew.bat buildPlugin
.\gradlew.bat compileKotlin --no-daemon
.\gradlew.bat test --no-daemon
```

The Gradle test task uses isolated IDEA sandbox paths. The current pure unit tests run through JUnit4/Vintage, which avoids IntelliJ JUnit5 `ThreadLeakTracker` startup failures in restricted Windows environments.

## Project Layout

- `config`: plugin settings and UI configuration
- `services`: backend client (`BackendClient`, `HttpBackendClient`)
- `model`: backend DTOs
- `ui.toolwindow`: chat UI, approvals, history, SSE handling
- `ui.dialogs`: feature generation and apply dialogs
- `actions`: scan/generate/apply actions
- `util`: project and path utilities

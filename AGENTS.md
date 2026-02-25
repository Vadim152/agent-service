# Repository Guidelines

## Project Structure & Module Organization
- `src/` contains the FastAPI backend:
  - `app/` startup, config, logging, and entrypoint (`app.main`).
  - `api/` HTTP routes and schemas (`routes_*.py`).
  - `agents/`, `chat/`, `self_healing/`, `infrastructure/`, `tools/`, `integrations/` for orchestration and domain logic.
- `tests/` contains Python `pytest` suites (API, startup, orchestration, integrations).
- `ide-plugin/` contains the IntelliJ plugin (Kotlin/Gradle) that integrates with this backend.
- Runtime artifacts are stored under `.agent/` and local vector data under `.chroma/` (both ignored by git).

## Build, Test, and Development Commands
- Backend setup:
  - `python -m venv .venv`
  - `.\.venv\Scripts\Activate.ps1`
  - `python -m pip install -e .`
- Run backend locally:
  - `agent-service`
  - alternative: `$env:PYTHONPATH="src"; python -m app.main`
- Run backend tests:
  - `python -m pytest -p no:cacheprovider`
  - example subset: `python -m pytest tests/test_jobs_api.py`
- Plugin commands (from `ide-plugin/`):
  - `.\gradlew.bat test` (plugin tests)
  - `.\gradlew.bat buildPlugin` (build distributable)

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indentation, type hints for public APIs, `snake_case` for functions/modules, `PascalCase` for classes.
- Keep route modules named `routes_<domain>.py`; keep tests named `test_<feature>.py`.
- Prefer small, composable functions and explicit configuration via `app/config.py` settings.
- Kotlin (plugin): follow Kotlin conventions (`PascalCase` types, `camelCase` members), keep DTOs under `model/`.

## Testing Guidelines
- Frameworks: `pytest` for backend, Gradle/JUnit for plugin.
- Add tests with each behavior change, especially for API contracts and job lifecycle states.
- Keep test files close to behavior (`tests/test_<area>.py`) and use clear test names like `test_<action>_<expected_result>()`.

## Commit & Pull Request Guidelines
- Use concise, imperative commit subjects (e.g., `Fix dependency resolution for editable install`).
- Optional prefixes are acceptable when useful (e.g., `chore: ...`).
- PRs should include:
  - what changed and why,
  - impacted endpoints/modules,
  - test evidence (commands run),
  - screenshots/GIFs for `ide-plugin` UI changes.

## Security & Configuration Tips
- Do not commit secrets; use `.env` with `AGENT_SERVICE_*` variables.
- Validate critical startup configuration locally via `GET /health` before opening a PR.

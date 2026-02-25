# agent-service

`agent-service` - FastAPI backend для IDE-плагина и CLI/HTTP-клиентов.

Сервис покрывает:
- сканирование и индексацию Cucumber-steps;
- генерацию `.feature` в `jobs-first` режиме;
- chat control-plane с SSE и workflow подтверждений;
- tool/memory/llm endpoint'ы;
- split-архитектуру Control Plane / Execution Plane / Tool Host.

Документация по IDE-плагину: `ide-plugin/README.md`.

## Состав репозитория

- `src/` - backend-код (`app`, `api`, `agents`, `chat`, `self_healing`, `infrastructure`).
- `tests/` - pytest тесты API, startup и runtime-компонентов.
- `ide-plugin/` - код IntelliJ-плагина.
- `.agent/` - локальные runtime-данные (индексы, артефакты).
- `.chroma/` - локальное vector-хранилище (если используется).

## Архитектура

```mermaid
flowchart LR
  subgraph Clients[Клиенты]
    IDE[IDE Plugin]
    CLI[CLI/HTTP]
  end

  subgraph CP[Control Plane (один сервис)]
    API[FastAPI API<br/>Runs • Sessions • SSE/WS]
    Policy[Tooling & Policy<br/>registry • approvals • audit]
    RunDB[(Postgres<br/>runs/attempts/events/sessions)]
    ArtIdx[(Artifacts index<br/>in DB)]
  end

  subgraph XP[Execution Plane]
    Q[Queue (опционально)<br/>Redis/RabbitMQ]
    W[Worker Pool<br/>(Executors)]
    Orch[Orchestrator Runtime<br/>(LangGraph)]
    RT[Runtime Plugins<br/>testgen • ift • debug • browser • analytics]
  end

  subgraph Tools[Tool Host (коннекторы)]
    Repo[Repo/Code access]
    Logs[Logs query]
    Art[Artifacts store]
    Browser[Playwright runner]
    Analytics[Analytics query]
    Patch[Patch proposal/apply]
  end

  subgraph Storage[Хранилища]
    OBJ[(S3/MinIO/FS<br/>artifacts, traces, screenshots)]
    VDB[(Vector store - опционально)]
    LOGS[(Log backend - опционально)]
    WARE[(Analytics warehouse - опционально)]
  end

  IDE --> API
  CLI --> API

  API --> RunDB
  API --> Policy

  API --> Q
  Q --> W
  W --> Orch
  Orch --> RT

  Orch --> Tools
  Tools --> OBJ
  Tools --> VDB
  Tools --> LOGS
  Tools --> WARE

  Patch --> Policy
  Art --> ArtIdx
```

Примечания по текущей реализации:
- queue backend в коде: `local` или `redis`;
- state backend: `memory` или `postgres`;
- Tool Host: `local` или `remote` (`/internal/tools/save-feature`);
- внешние хранилища (`S3`, `VDB`, `LOGS`, `WARE`) пока опциональны и подключаются по мере интеграций.

## Режимы запуска

### 1) Single-process (локальная разработка, по умолчанию)

- `state_backend=memory`
- `execution_backend=local`
- `tool_host_mode=local`

В этом режиме `POST /jobs` выполняется внутри процесса API.

### 2) Split CP/XP/Tool Host (рекомендуемый production-путь)

- Control Plane: `agent-service`
- Execution Plane worker: `agent-service-worker`
- Tool Host: `agent-service-tool-host`
- Рекомендуемые backend'ы: `state_backend=postgres`, `execution_backend=queue`, `queue_backend=redis`, `tool_host_mode=remote`

## Требования

- Python `>=3.10`
- PowerShell (или любой shell с эквивалентными командами)

Опциональные зависимости по режимам:
- `redis` - нужен для `AGENT_SERVICE_QUEUE_BACKEND=redis`;
- `psycopg` - нужен для `AGENT_SERVICE_STATE_BACKEND=postgres`.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
```

## Запуск

### Локальный single-process

```powershell
agent-service
```

Альтернатива:

```powershell
$env:PYTHONPATH="src"
python -m app.main
```

### Split: Control Plane + Worker + Tool Host

Пример env:

```powershell
$env:AGENT_SERVICE_STATE_BACKEND='postgres'
$env:AGENT_SERVICE_POSTGRES_DSN='postgresql://postgres:postgres@127.0.0.1:5432/agent_service'
$env:AGENT_SERVICE_EXECUTION_BACKEND='queue'
$env:AGENT_SERVICE_QUEUE_BACKEND='redis'
$env:AGENT_SERVICE_REDIS_URL='redis://127.0.0.1:6379/0'
$env:AGENT_SERVICE_TOOL_HOST_MODE='remote'
$env:AGENT_SERVICE_TOOL_HOST_URL='http://127.0.0.1:8001'
```

Терминал 1 (Control Plane):

```powershell
agent-service
```

Терминал 2 (Execution Plane worker):

```powershell
agent-service-worker
```

Терминал 3 (Tool Host):

```powershell
agent-service-tool-host
```

Для тестового комбинированного режима можно включить встроенный worker:

```powershell
$env:AGENT_SERVICE_EXECUTION_BACKEND='queue'
$env:AGENT_SERVICE_QUEUE_BACKEND='local'
$env:AGENT_SERVICE_EMBEDDED_EXECUTION_WORKER='true'
agent-service
```

## Readiness / Health

```powershell
curl http://127.0.0.1:8000/health
```

- во время startup: `503`, `status=initializing`;
- после успешной инициализации: `200`, `status=ok`.

## Базовый URL API

Все внешние API-route'ы публикуются с префиксом `AGENT_SERVICE_API_PREFIX` (по умолчанию `/api/v1`).

Пример: `POST /jobs` доступен как `POST /api/v1/jobs`.

## Обзор API

### Steps API

- `POST /steps/scan-steps`
- `GET /steps/?projectRoot=...`

### Feature API (legacy synchronous)

- `POST /feature/generate-feature`
- `POST /feature/apply-feature`

### Jobs API (основной асинхронный путь)

- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/attempts`
- `GET /jobs/{job_id}/result`
- `POST /jobs/{job_id}/cancel`
- `GET /jobs/{job_id}/events` (SSE)

### Chat API

- `POST /chat/sessions`
- `GET /chat/sessions?projectRoot=...`
- `POST /chat/sessions/{session_id}/messages`
- `POST /chat/sessions/{session_id}/tool-decisions`
- `GET /chat/sessions/{session_id}/history`
- `GET /chat/sessions/{session_id}/status`
- `GET /chat/sessions/{session_id}/diff`
- `POST /chat/sessions/{session_id}/commands`
- `GET /chat/sessions/{session_id}/stream` (SSE)

### Tools / Memory / LLM API

- `POST /tools/find-steps`
- `POST /tools/compose-autotest`
- `POST /tools/explain-unmapped`
- `POST /memory/feedback`
- `POST /llm/test`

### Tool Host internal API

- `POST /internal/tools/save-feature` (`agent-service-tool-host`)

## Jobs-first поток генерации

Основной сценарий:
1. `POST /jobs` с `projectRoot`, `testCaseText`, профилем и опциями.
2. Отслеживание статуса через `GET /jobs/{job_id}` или SSE `GET /jobs/{job_id}/events`.
3. Получение результата через `GET /jobs/{job_id}/result`.

Поведение:
- до готовности результата `GET /jobs/{job_id}/result` вернет `409`;
- поддерживается `Idempotency-Key` в `POST /jobs`:
  - тот же ключ + тот же payload -> возвращается существующий `jobId`;
  - тот же ключ + другой payload -> `409`.

Типичный lifecycle:
- `queued -> running -> succeeded | needs_attention | cancelled`
- при отмене возможен промежуточный `cancelling`.

Attempt-level статусы:
- `started`
- `succeeded`
- `failed`
- `remediated`
- `rerun_scheduled`
- `cancelled`

## Ключевые переменные окружения

### Базовые

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AGENT_SERVICE_APP_NAME` | `agent-service` | Имя сервиса |
| `AGENT_SERVICE_API_PREFIX` | `/api/v1` | Префикс API |
| `AGENT_SERVICE_HOST` | `127.0.0.1` | Host bind |
| `AGENT_SERVICE_PORT` | `8000` | Port bind |
| `AGENT_SERVICE_LOG_REQUEST_BODIES` | `false` | Логировать body входящих запросов |
| `AGENT_SERVICE_STEPS_INDEX_DIR` | `.agent/steps_index` | Каталог индекса шагов |
| `AGENT_SERVICE_ARTIFACTS_DIR` | `.agent/artifacts` | Каталог job artifacts |

### Архитектура / Split

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AGENT_SERVICE_STATE_BACKEND` | `memory` | `memory` или `postgres` |
| `AGENT_SERVICE_POSTGRES_DSN` | `null` | DSN Postgres (обязательно при `state_backend=postgres`) |
| `AGENT_SERVICE_EXECUTION_BACKEND` | `local` | `local` или `queue` |
| `AGENT_SERVICE_QUEUE_BACKEND` | `local` | `local` или `redis` |
| `AGENT_SERVICE_QUEUE_NAME` | `agent-service:jobs` | Название очереди |
| `AGENT_SERVICE_REDIS_URL` | `redis://127.0.0.1:6379/0` | URL Redis (нужен при `queue_backend=redis`) |
| `AGENT_SERVICE_EMBEDDED_EXECUTION_WORKER` | `false` | Поднять worker внутри CP-процесса |
| `AGENT_SERVICE_TOOL_HOST_MODE` | `local` | `local` или `remote` |
| `AGENT_SERVICE_TOOL_HOST_URL` | `null` | Base URL remote Tool Host (обязательно при `tool_host_mode=remote`) |

### Jira / testcase source

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AGENT_SERVICE_JIRA_SOURCE_MODE` | `stub` | Режим источника testcase (`stub/live/disabled`) |
| `AGENT_SERVICE_JIRA_REQUEST_TIMEOUT_S` | `20` | HTTP timeout к Jira |
| `AGENT_SERVICE_JIRA_DEFAULT_INSTANCE` | `https://jira.sberbank.ru` | Jira instance по умолчанию |
| `AGENT_SERVICE_JIRA_VERIFY_SSL` | `true` | Проверка TLS Jira |
| `AGENT_SERVICE_JIRA_CA_BUNDLE_FILE` | `null` | Кастомный CA bundle для Jira |

### LLM / GigaChat / Corp proxy

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AGENT_SERVICE_LLM_ENDPOINT` | `null` | Endpoint внешнего LLM |
| `AGENT_SERVICE_LLM_API_KEY` | `null` | API-ключ внешнего LLM |
| `AGENT_SERVICE_LLM_MODEL` | `null` | Модель внешнего LLM |
| `AGENT_SERVICE_LLM_API_VERSION` | `null` | Версия API внешнего LLM |
| `GIGACHAT_CLIENT_ID` / `AGENT_SERVICE_GIGACHAT_CLIENT_ID` | `null` | OAuth client id |
| `GIGACHAT_CLIENT_SECRET` / `AGENT_SERVICE_GIGACHAT_CLIENT_SECRET` | `null` | OAuth client secret |
| `GIGACHAT_SCOPE` / `AGENT_SERVICE_GIGACHAT_SCOPE` | `GIGACHAT_API_PERS` | OAuth scope |
| `GIGACHAT_AUTH_URL` / `AGENT_SERVICE_GIGACHAT_AUTH_URL` | `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` | OAuth endpoint |
| `GIGACHAT_API_URL` / `AGENT_SERVICE_GIGACHAT_API_URL` | `https://gigachat.devices.sberbank.ru/api/v1` | API endpoint |
| `GIGACHAT_VERIFY_SSL` / `AGENT_SERVICE_GIGACHAT_VERIFY_SSL` | `true` | Проверка TLS GigaChat |
| `AGENT_SERVICE_CORP_MODE` | `false` | Включить corp proxy mode |
| `AGENT_SERVICE_CORP_PROXY_HOST` | `null` | Хост прокси (`scheme + host`) |
| `AGENT_SERVICE_CORP_PROXY_PATH` | `/sbe-ai-pdlc-integration-code-generator/v1/chat/proxy/completions` | Путь proxy endpoint |
| `AGENT_SERVICE_CORP_MODEL` | `GigaChat-2-Max` | Модель в corp-режиме |
| `AGENT_SERVICE_CORP_CERT_FILE` | `null` | Клиентский cert для mTLS |
| `AGENT_SERVICE_CORP_KEY_FILE` | `null` | Клиентский key для mTLS |
| `AGENT_SERVICE_CORP_CA_BUNDLE_FILE` | `null` | CA bundle для TLS |
| `AGENT_SERVICE_CORP_REQUEST_TIMEOUT_S` | `30.0` | Timeout запросов к proxy |
| `AGENT_SERVICE_CORP_RETRY_ATTEMPTS` | `3` | Количество retry |
| `AGENT_SERVICE_CORP_RETRY_BASE_DELAY_S` | `0.5` | Базовая задержка retry |
| `AGENT_SERVICE_CORP_RETRY_MAX_DELAY_S` | `4.0` | Максимальная задержка retry |
| `AGENT_SERVICE_CORP_RETRY_JITTER_S` | `0.2` | Jitter retry |

### Тюнинг matcher

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AGENT_SERVICE_MATCH_RETRIEVAL_TOP_K` | `50` | Top-K retrieval кандидатов |
| `AGENT_SERVICE_MATCH_CANDIDATE_POOL` | `30` | Размер пула после префильтра |
| `AGENT_SERVICE_MATCH_THRESHOLD_EXACT` | `0.8` | Порог exact |
| `AGENT_SERVICE_MATCH_THRESHOLD_FUZZY` | `0.5` | Порог fuzzy |
| `AGENT_SERVICE_MATCH_MIN_SEQ_FOR_EXACT` | `0.72` | Мин. seq score для exact |
| `AGENT_SERVICE_MATCH_AMBIGUITY_GAP` | `0.08` | Порог неоднозначности top1-top2 |
| `AGENT_SERVICE_MATCH_LLM_MIN_SCORE` | `0.45` | Нижняя граница зоны LLM rerank |
| `AGENT_SERVICE_MATCH_LLM_MAX_SCORE` | `0.82` | Верхняя граница зоны LLM rerank |
| `AGENT_SERVICE_MATCH_LLM_SHORTLIST` | `5` | Размер shortlist в LLM rerank |
| `AGENT_SERVICE_MATCH_LLM_MIN_CONFIDENCE` | `0.7` | Мин. уверенность LLM rerank |

## Проверка тестами

Полный прогон:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider
```

Ключевые smoke-наборы:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider tests/test_jobs_api.py tests/test_chat_api.py tests/test_job_dispatcher.py tests/test_tool_host_split.py tests/test_startup_readiness.py
```

## Troubleshooting

### `Result is not ready` (`409`) на `/jobs/{job_id}/result`

Job еще не в terminal-статусе. Используйте polling `/jobs/{job_id}` или SSE `/jobs/{job_id}/events`.

### `projectRoot is required` (`422`) на `/steps/scan-steps`

Проверьте `projectRoot` в body/query и существование пути на диске.

### Ошибка `Redis backend requires 'redis' package`

Установите зависимость:

```powershell
python -m pip install redis
```

### Ошибка `Postgres backend requires 'psycopg' package`

Установите зависимость:

```powershell
python -m pip install "psycopg[binary]"
```

## Безопасность

- Не коммитьте секреты: используйте `.env` и переменные `AGENT_SERVICE_*`.
- Для TLS корпоративной сети используйте `*_CA_BUNDLE_FILE`, а не отключение SSL-проверки.

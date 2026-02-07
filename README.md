# agent-service

Backend для Sber IDE плагина, который помогает:

- сканировать репозиторий на Cucumber/BDD шаги;
- сопоставлять шаги тесткейса с найденными определениями;
- генерировать и сохранять `.feature` файл (Gherkin);
- запускать полный цикл через единый Job API (контрольный контур + события).

Сервис построен на FastAPI и использует набор агентных компонентов, объединенных в оркестратор.

## Архитектура

### Оркестратор и агенты

- **RepoScannerAgent** — сканирует репозиторий и индексирует шаги (`**/*Steps.{java,kt,groovy,py}`).
- **TestcaseParserAgent** — разбирает текст тесткейса в структурированный сценарий (LLM + эвристики).
- **StepMatcherAgent** — сопоставляет шаги тесткейса с индексом Cucumber-шагов.
- **FeatureBuilderAgent** — собирает доменную модель `.feature` и рендерит Gherkin.

### Хранилища

- **StepIndexStore** — индекс шагов в `.agent/steps_index`.
- **EmbeddingsStore** — эмбеддинги шагов в ChromaDB для семантического поиска.
- **RunStateStore** — состояние Job API (статусы, попытки, события).
- **ArtifactStore** — артефакты запусков (результаты, классификации, инциденты).

### LLM

По умолчанию используется GigaChat-адаптер. Если учетные данные не заданы, сервис работает в fallback-режиме.

## Запуск

### Локально (Windows PowerShell)

```powershell
cd C:\path\to\agent-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .

python -m app.main
```

### Локально (Linux/macOS)

```bash
cd /path/to/agent-service
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .

python -m app.main
```

## Переменные окружения

Все настройки читаются с префиксом `AGENT_SERVICE_` (или из `.env`).

| Переменная                      | Назначение                         | Значение по умолчанию                               |
|---------------------------------|------------------------------------|-----------------------------------------------------|
| `AGENT_SERVICE_APP_NAME`        | Имя сервиса                        | `agent-service`                                     |
| `AGENT_SERVICE_API_PREFIX`      | Префикс HTTP API                   | `/api/v1`                                           |
| `AGENT_SERVICE_HOST`            | Хост приложения                    | `0.0.0.0`                                           |
| `AGENT_SERVICE_PORT`            | Порт приложения                    | `8000`                                              |
| `AGENT_SERVICE_STEPS_INDEX_DIR` | Папка индекса шагов                | `.agent/steps_index`                                |
| `AGENT_SERVICE_LLM_ENDPOINT`    | Endpoint LLM (если нужен)          | `None`                                              |
| `AGENT_SERVICE_LLM_API_KEY`     | API ключ LLM                       | `None`                                              |
| `AGENT_SERVICE_LLM_MODEL`       | Модель LLM                         | `None`                                              |
| `AGENT_SERVICE_LLM_API_VERSION` | Версия API LLM                     | `None`                                              |
| `GIGACHAT_CLIENT_ID`            | Client ID для GigaChat             | `None`                                              |
| `GIGACHAT_CLIENT_SECRET`        | Client Secret для GigaChat         | `None`                                              |
| `GIGACHAT_SCOPE`                | OAuth scope GigaChat               | `GIGACHAT_API_PERS`                                 |
| `GIGACHAT_AUTH_URL`             | OAuth endpoint GigaChat            | `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` |
| `GIGACHAT_API_URL`              | API endpoint GigaChat              | `https://gigachat.devices.sberbank.ru/api/v1`       |
| `GIGACHAT_VERIFY_SSL`           | Проверять SSL сертификаты GigaChat | `false`                                             |

Важно: не храните реальные секреты в репозитории. Используйте `.env` локально или CI-секреты.

## HTTP API

Базовый префикс API настраивается через `AGENT_SERVICE_API_PREFIX` (по умолчанию `/api/v1`).

### Healthcheck

```bash
curl -X GET http://0.0.0.0:8000/health
```

### Job API (основной поток для плагина)

#### Создать job

```bash
curl -X POST http://0.0.0.0:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot": "/path/to/project",
    "testCaseText": "1. Открыть страницу\n2. Нажать кнопку",
    "targetPath": "features/generated.feature",
    "createFile": true,
    "overwriteExisting": false,
    "language": "ru",
    "profile": "quick",
    "source": "sber-ide"
  }'
```

Ответ: `{ "jobId": "...", "status": "queued" }`

#### Получить статус job

```bash
curl -X GET http://0.0.0.0:8000/api/v1/jobs/{jobId}
```

#### Получить результат job

```bash
curl -X GET http://0.0.0.0:8000/api/v1/jobs/{jobId}/result
```

Если результат еще не готов, возвращается `409`.

#### Получить попытки job

```bash
curl -X GET http://0.0.0.0:8000/api/v1/jobs/{jobId}/attempts
```

#### События job (SSE)

```bash
curl -N http://0.0.0.0:8000/api/v1/jobs/{jobId}/events
```

Основные события:

- `job.queued`, `job.running`, `job.finished`
- `attempt.started`, `attempt.succeeded`, `attempt.classified`, `attempt.remediated`, `attempt.rerun_scheduled`
- `job.incident`

### Сканирование шагов

```bash
curl -X POST http://0.0.0.0:8000/api/v1/steps/scan-steps \
  -H "Content-Type: application/json" \
  -d '{"projectRoot": "/path/to/project"}'
```

Получение сохраненных шагов:

```bash
curl -X GET "http://0.0.0.0:8000/api/v1/steps/?projectRoot=/path/to/project"
```

### Ручная генерация `.feature`

Основной поток для плагина идет через Job API, но ручные endpoint'ы доступны для отладки.

```bash
curl -X POST http://0.0.0.0:8000/api/v1/feature/generate-feature \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot": "/path/to/project",
    "testCaseText": "1. Открыть страницу\n2. Нажать кнопку",
    "targetPath": "features/generated.feature",
    "options": {
      "createFile": true,
      "overwriteExisting": false,
      "language": "ru"
    }
  }'
```

### Сохранение `.feature` файла

```bash
curl -X POST http://0.0.0.0:8000/api/v1/feature/apply-feature \
  -H "Content-Type: application/json" \
  -d '{
    "projectRoot": "/path/to/project",
    "targetPath": "features/generated.feature",
    "featureText": "# language: ru\nФункционал: ...",
    "overwriteExisting": false
  }'
```

### Проверка LLM

```bash
curl -X POST http://0.0.0.0:8000/api/v1/llm/test \
  -H "Content-Type: application/json" \
  -d '{"prompt":"ping"}'
```

## Сборка плагина

Windows:

```powershell
.\ide-plugin\gradlew.bat -p ide-plugin buildPlugin
```

Linux/macOS:

```bash
./ide-plugin/gradlew -p ide-plugin buildPlugin
```

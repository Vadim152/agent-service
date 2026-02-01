# agent-service

Backend-сервис для плагина Sber IDE, который помогает:
- сканировать проект на Cucumber/BDD шаги;
- сопоставлять шаги тесткейса с найденными определениями;
- генерировать `.feature` файл (Gherkin) и сохранять его в проекте.

Сервис построен на FastAPI и использует набор агентов, объединённых в оркестратор на базе LangGraph.

## Архитектура

### Оркестратор и агенты

Оркестратор запускает цепочки задач, которые реализованы агентами:
- **RepoScannerAgent** — сканирует репозиторий и индексирует шаги (`**/*Steps.{java,kt,groovy,py}`).
- **TestcaseParserAgent** — разбирает текст тесткейса в структурированный сценарий (LLM + эвристики).
- **StepMatcherAgent** — сопоставляет шаги тесткейса с индексом Cucumber-шагов.
- **FeatureBuilderAgent** — собирает доменную модель `.feature` и рендерит Gherkin.

### Хранилища

- **StepIndexStore** — хранит индекс шагов в каталоге `.agent/steps_index`.
- **EmbeddingsStore** — хранит эмбеддинги шагов в ChromaDB для семантического поиска.

### LLM

По умолчанию используется GigaChat-адаптер. При отсутствии учётных данных сервис переходит в fallback-режим: LLM-возможности будут ограничены, но основной пайплайн продолжит работать.

## Запуск

### Локальный запуск

```bash
cd /workspace/agent-service
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .

uvicorn app.main:app --host 0.0.0.0 --port 8000
# либо
agent-service
```

### Переменные окружения

Все настройки читаются с префиксом `AGENT_SERVICE_` (или из `.env`).

| Переменная | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `AGENT_SERVICE_APP_NAME` | Имя сервиса | `agent-service` |
| `AGENT_SERVICE_API_PREFIX` | Префикс HTTP API | `/api/v1` |
| `AGENT_SERVICE_HOST` | Хост приложения | `0.0.0.0` |
| `AGENT_SERVICE_PORT` | Порт приложения | `8000` |
| `AGENT_SERVICE_STEPS_INDEX_DIR` | Папка индекса шагов | `.agent/steps_index` |
| `AGENT_SERVICE_LLM_ENDPOINT` | Endpoint LLM (если нужен) | `None` |
| `AGENT_SERVICE_LLM_API_KEY` | API ключ LLM | `None` |
| `AGENT_SERVICE_LLM_MODEL` | Модель LLM | `None` |
| `AGENT_SERVICE_LLM_API_VERSION` | Версия API LLM | `None` |
| `GIGACHAT_CLIENT_ID` | Client ID для GigaChat | `None` |
| `GIGACHAT_CLIENT_SECRET` | Client Secret для GigaChat | `None` |
| `GIGACHAT_SCOPE` | OAuth scope GigaChat | `GIGACHAT_API_PERS` |
| `GIGACHAT_AUTH_URL` | OAuth endpoint GigaChat | `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` |
| `GIGACHAT_API_URL` | API endpoint GigaChat | `https://gigachat.devices.sberbank.ru/api/v1` |
| `GIGACHAT_VERIFY_SSL` | Проверять SSL сертификаты GigaChat | `false` |

> ⚠️ Не храните реальные секреты в репозитории. Используйте `.env` локально или CI-секреты.

## HTTP API

Базовый префикс настраивается через `AGENT_SERVICE_API_PREFIX` (по умолчанию `/api/v1`).

### Healthcheck

```bash
curl -X GET http://0.0.0.0:8000/health
```

### Сканирование шагов

```bash
curl -X POST http://0.0.0.0:8000/api/v1/steps/scan-steps \
  -H "Content-Type: application/json" \
  -d '{"projectRoot": "/path/to/project"}'
```

Получение сохранённых шагов:

```bash
curl -X GET "http://0.0.0.0:8000/api/v1/steps/?projectRoot=/path/to/project"
```

### Генерация `.feature`

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

```bash
./gradlew build
./ide-plugin/gradlew -p ide-plugin buildPlugin
```

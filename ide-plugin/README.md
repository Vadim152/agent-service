# Агентум (ide-plugin)

`ide-plugin` - IntelliJ Platform плагин, который работает с backend `agent-service`.
Текущий фокус плагина:
- Tool Window для чата с агентом;
- работа с chat control-plane (`/chat/*`, SSE stream, approvals);
- сканирование шагов Cucumber из UI настроек;
- генерация/применение `.feature` через backend-клиент (jobs-first для генерации).

## Что реально зарегистрировано в IDE

Согласно `src/main/resources/META-INF/plugin.xml`:
- Tool Window `Агентум`;
- Project Settings страница `Tools -> Агентум`;
- notification group `Агентум`.

## Возможности Tool Window

`AiToolWindowPanel` реализует:
- создание новой chat-сессии (`+`) и переиспользование существующей;
- экран истории сессий и переключение между ними;
- отправку сообщений в backend;
- SSE-подписку на `/chat/sessions/{sessionId}/stream` с авто-reconnect;
- отображение `pendingPermissions` и отправку решений (`approve_once`, `approve_always`, `reject`);
- отображение прогресса по activity (`busy`, `retry`, `waiting_permission`, `idle`, `error`);
- быстрые slash-шаблоны (`/autotest`, `/unmapped`, `/save`).

Примечание:
- кнопка отправки в состоянии генерации отправляет команду `abort` через `/chat/sessions/{sessionId}/commands`.

## Настройки плагина

`AiTestPluginSettings` хранит:
- `backendUrl` (по умолчанию `http://localhost:8000/api/v1`);
- timeout'ы (`requestTimeoutMs`, `chatSendTimeoutMs`, `generateFeatureTimeoutMs`);
- параметры Zephyr/Jira авторизации;
- значения для scan/generate/apply сценариев.

UI (`AiTestPluginSettingsConfigurable`) сейчас редактирует:
- `scanProjectRoot`;
- Zephyr auth mode (`TOKEN` или `LOGIN_PASSWORD`);
- Jira instance (сейчас предустановлен `Sigma -> https://jira.sberbank.ru`);
- список Jira-проектов и проверку доступа к проекту.

Текущее ограничение:
- в UI нет полей для `backendUrl` и timeout'ов, хотя в настройках они есть и используются клиентом.

## Интеграция с backend

`HttpBackendClient` обращается к endpoint'ам:
- `POST /steps/scan-steps?projectRoot=...`
- `GET /steps/?projectRoot=...`
- `POST /feature/generate-feature`
- `POST /jobs`
- `GET /jobs/{jobId}`
- `GET /jobs/{jobId}/result`
- `POST /feature/apply-feature`
- `POST /chat/sessions`
- `GET /chat/sessions`
- `POST /chat/sessions/{sessionId}/messages`
- `GET /chat/sessions/{sessionId}/history`
- `GET /chat/sessions/{sessionId}/status`
- `GET /chat/sessions/{sessionId}/diff`
- `POST /chat/sessions/{sessionId}/commands`
- `POST /chat/sessions/{sessionId}/tool-decisions`
- `GET /chat/sessions/{sessionId}/stream`
- `GET /jobs/{jobId}/events` (SSE для ожидания terminal статуса job)

## Потоки работы

### 1) Чат в Tool Window

1. Плагин создает/переиспользует сессию `POST /chat/sessions` (`source=ide-plugin`, `profile=quick`).
2. Отправка сообщения: `POST /chat/sessions/{sessionId}/messages`.
3. Обновление UI через SSE stream и периодический refresh (`history` + `status`).
4. При запросе подтверждения пользователь выбирает действие, плагин вызывает `POST /chat/sessions/{sessionId}/tool-decisions`.

### 2) Сканирование шагов

1. В Settings пользователь задает `projectRoot` и нажимает "Сканировать шаги".
2. Плагин вызывает `POST /steps/scan-steps`.
3. Затем загружает/показывает индекс шагов в UI.

### 3) Генерация feature (jobs-first)

`GenerateFeatureFromSelectionAction` делает:
1. `POST /jobs`.
2. Ожидание terminal статуса (`/jobs/{id}/events`, fallback polling `/jobs/{id}`).
3. `GET /jobs/{id}/result`.
4. Открытие результата в редакторе и подсветка `unmapped` шагов.

### 4) Применение feature

`ApplyFeatureAction` отправляет `POST /feature/apply-feature` и показывает статус `created/overwritten/rejected_outside_project`.

## Важные ограничения

- В `plugin.xml` нет секции `<actions>`, поэтому action-классы из `actions/*` не зарегистрированы как пункты меню IDE на уровне descriptor.
- Placeholder в input (`#`, `@`) присутствует, но специализированной обработки этих префиксов в панели сейчас нет; реализованы только slash-шаблоны.
- В UI настроек доступен только Jira instance `Sigma`.

## Сборка и запуск

Требования:
- JDK `17` (`kotlin.jvmToolchain(17)`)
- IntelliJ target `2025.1` (`sinceBuild = 251`)

Команды запускать из каталога `ide-plugin`.

Сборка плагина:

```powershell
.\gradlew.bat buildPlugin
```

Запуск sandbox IDE:

```powershell
.\gradlew.bat runIde
```

Тесты:

```powershell
.\gradlew.bat test
```

## Структура кода

- `config` - настройки плагина и UI конфигурации.
- `services` - backend-клиент (`BackendClient`, `HttpBackendClient`).
- `model` - DTO для API backend.
- `ui.toolwindow` - основная панель чата, история, approvals, SSE.
- `ui.dialogs` - диалоги параметров генерации/применения feature.
- `actions` - action-классы для scan/generate/apply сценариев.
- `util` - утилиты работы с проектом и scan roots.

## Диагностика

- Проверьте, что backend доступен по `backendUrl` (по умолчанию `http://localhost:8000/api/v1`).
- Для проблем чата проверьте endpoint'ы `/chat/sessions/*` и SSE `/chat/sessions/{id}/stream`.
- Для проблем генерации проверьте `/jobs/*` и наличие актуального индекса шагов (`/steps/scan-steps`).

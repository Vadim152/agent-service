# Пошаговый план внедрения расширяемой self-healing системы в `agent-service`

Документ — «исполняемый чеклист». Проходишь шаг за шагом и получаешь систему, которая:
1) запускает прогон,
2) анализирует сбой,
3) применяет авто-ремедиацию,
4) перезапускает прогон,
5) при необходимости уходит в логи/аналитику и формирует отчёт.

---

## Шаг 1. Зафиксировать целевую модель домена и статусы

**Сделать:**
- Ввести сущности: `Job`, `Run`, `RunAttempt`, `FailureClassification`, `RemediationAction`, `IncidentReport`.
- Ввести статусы:
  - `Job`: `queued`, `running`, `needs_attention`, `succeeded`, `failed`;
  - `RunAttempt`: `started`, `failed`, `remediated`, `rerun_scheduled`, `succeeded`.
- Добавить `correlation fields`: `jobId`, `runId`, `attemptId`, `source`.

**Критерий готовности:**
- Все новые поля сериализуются в API-схемы и попадают в логи.

---

## Шаг 2. Ввести Job API как единый вход (control plane)

**Сделать:**
- Реализовать:
  - `POST /jobs` (создание и старт),
  - `GET /jobs/{jobId}` (состояние),
  - `GET /jobs/{jobId}/events` (SSE/WebSocket поток),
  - `POST /jobs/{jobId}/cancel`.
- Текущие маршруты `/steps/*` и `/feature/*` постепенно проксировать на Job API.

**Критерий готовности:**
- IDE-плагин и CLI одинаково работают через `jobId` и получают поток прогресса.

---

## Шаг 3. Добавить RunStateStore и ArtifactStore

**Сделать:**
- `RunStateStore`: хранение статусов job/run/attempt + временные метки.
- `ArtifactStore`: stdout/stderr, json-репорты, feature-артефакты, логи классификации ошибки.
- Везде писать ссылки на артефакты вместо «сырая простыня в ответе API».

**Критерий готовности:**
- По `jobId` можно восстановить историю попыток и все артефакты.

---

## Шаг 4. Развернуть capability registry

**Сделать:**
- Зарегистрировать capability как изолированные контракты:
  - `scan_steps`, `parse_testcase`, `match_steps`, `build_feature`, `apply_feature`,
  - `run_test_execution`, `collect_run_artifacts`, `classify_failure`, `apply_remediation`, `rerun_with_strategy`, `incident_report_builder`.
- Оркестратор собирает pipeline по профилю (`quick`, `strict`, `ci`).

**Критерий готовности:**
- Новая capability подключается без изменения ядра оркестратора.

---

## Шаг 5. Ввести failure taxonomy + классификатор

**Сделать:**
- Зафиксировать классы ошибок: infra/env/data/flaky/product/automation.
- Реализовать `classify_failure`:
  - вход: артефакты запуска,
  - выход: тип ошибки + confidence + признаки.
- Если confidence низкий — помечать `needs_attention`.

**Критерий готовности:**
- Каждому failed-attempt присваивается класс ошибки (или явный unknown).

---

## Шаг 6. Реализовать remediation playbooks

**Сделать:**
- Для каждого класса ошибок создать allowlist действий:
  - infra → backoff retry;
  - flaky → rerun в isolated режиме;
  - env/data → безопасный reset/provision;
  - automation → включить verbose/debug + собрать доп. контекст.
- Запретить опасные действия политиками (никаких непредсказуемых мутаций).

**Критерий готовности:**
- На типовой flaky/infra ошибке система может сама довести прогон до green или корректно эскалировать.

---

## Шаг 7. Построить ExecutionSupervisor (state machine)

**Сделать:**
- Явная машина состояний:
  `run -> failed -> classify -> remediate -> rerun -> success|escalate`.
- Ограничения:
  - `max_auto_reruns`;
  - `max_total_duration`;
  - stop conditions.

**Критерий готовности:**
- Нет бесконечных retry-циклов, все переходы прозрачны и аудируемы.

---

## Шаг 8. Включить observability-first

**Сделать:**
- Structured logs (JSON) с обязательными `jobId/runId/attemptId`.
- Метрики:
  - success rate,
  - rerun success uplift,
  - flaky ratio,
  - MTTR.
- Трейсинг (OpenTelemetry) для внешних вызовов и агентов.

**Критерий готовности:**
- По одному `jobId` в observability-стеке видно полный путь и узкое место.

---

## Шаг 9. Интеграция с логами и аналитикой

**Сделать:**
- Подключить sink в лог-сервис (ELK/Loki/аналог).
- Подключить метрики в Prometheus/Grafana.
- Ошибки и контекст в Sentry/аналог.
- Сделать `incident_report_builder` (краткая RCA-выжимка).

**Критерий готовности:**
- При неуспехе после авто-ремедиации система выдаёт готовый инцидент-отчёт с гипотезами.

---

## Шаг 10. UI/IDE опыт: понятный live-статус

**Сделать:**
- В IDE-плагине показывать этапы:
  - «Запуск»,
  - «Диагностика»,
  - «Авто-ремедиация»,
  - «Повторный запуск»,
  - «Эскалация».
- Добавить кнопку: «Открыть связанные логи/дашборд/инцидент».

**Критерий готовности:**
- Пользователь видит не «упало», а детальный narrative того, что система сделала и почему.

---

## Шаг 11. Ввести quality gates и release strategy

**Сделать:**
- Quality gates перед релизом функции auto-remediation:
  - precision классификации,
  - доля успешных rerun,
  - ограничение ложных ремедиаций.
- Раскатка фичи через feature flags:
  - сначала `shadow mode` (без действия),
  - затем limited rollout,
  - затем default-on.

**Критерий готовности:**
- Возможность безопасно откатить/ограничить автоматические действия в любой момент.

---

## Шаг 12. Финализация: runbooks и ownership

**Сделать:**
- Описать runbooks для QA/SRE/разработки.
- Назначить ownership по зонам:
  - policy engine,
  - классификатор,
  - observability,
  - integration с CI.
- Добавить еженедельный review метрик self-healing.

**Критерий готовности:**
- Система не только работает, но и поддерживается организационно.

---

## Минимальный MVP (если нужно быстро)

Если нужно внедрить в 2-3 итерации:
1. Шаги 1-3 (Job API + state/artifacts),
2. Шаги 5-7 (классификация + простые playbooks + supervisor),
3. Шаги 8-10 (observability + live-status в IDE).

Это уже даст «openclaw-подобное» поведение расширяемой control-plane системы с базовым self-healing циклом.

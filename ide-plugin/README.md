# AI Cucumber Assistant (Sber IDE plugin skeleton)

Этот модуль описывает каркас плагина для Sber IDE/IntelliJ Platform, который обращается к backend-сервису `agent-service`.

Основные сценарии:
- Сканирование шагов Cucumber через `/steps/scan-steps` и отображение в Tool Window.
- Генерация `.feature` по выделенному тексту тесткейса через `/feature/generate-feature`.
- Применение сгенерированного `.feature` через `/feature/apply-feature`.

Структура пакетов:
- `config` — настройки плагина и UI для конфигурации URL backend.
- `services` — HTTP-клиент и доступ к backend.
- `model` — DTO для сериализации/десериализации запросов и ответов.
- `ui.toolwindow` — Tool Window "AI Cucumber Assistant".
- `actions` — действия для меню/toolbar/контекстного меню.
- `util` — вспомогательные утилиты (поиск корня проекта, уведомления и т.п.).

Реализации — заглушки, отмеченные TODO, чтобы позже добавить реальный HTTP-клиент, фоновую работу и обработку ошибок.

## Потоки взаимодействия

### Сканирование шагов через Tool Window
1. Пользователь открывает Tool Window "AI Cucumber Assistant".
2. Указывает/оставляет projectRoot и нажимает "Scan steps".
3. Плагин вызывает `BackendClient.scanSteps` → `/steps/scan-steps`.
4. Backend индексирует шаги и возвращает счётчик/примеры; UI обновляет таблицу и статус.

### Генерация feature из выделенного тесткейса
1. Пользователь выделяет текст тесткейса в редакторе и запускает action "Generate Feature from Test Case".
2. Открывается диалог с targetPath/createFile/overwriteExisting. Последние выбранные значения сохраняются в настройках плагина и подставляются при следующем вызове.
3. Плагин формирует `GenerateFeatureRequestDto` и вызывает `BackendClient.generateFeature` → `/feature/generate-feature`.
4. Backend парсит, матчит шаги, формирует featureText и опционально сохраняет файл.
5. Плагин открывает featureText в редакторе/показывает результат, unmapped steps отображаются позже (TODO).

### Применение feature-файла
1. Пользователь редактирует/просматривает feature-текст в редакторе.
2. Action "Apply Feature" открывает диалог с targetPath/createFile/overwriteExisting (значения также запоминаются) и вызывает `/feature/apply-feature` через `BackendClient.applyFeature`.
3. Backend создаёт/перезаписывает файл и возвращает статус (created/overwritten/skipped), который показывается в IDE.

# agent-service

## Тестовый эндпоинт LLM
- Путь: `POST {api_prefix}/llm/test`.
- Значение `api_prefix` по умолчанию — `/api/v1`, настройка доступна через переменную окружения `AGENT_SERVICE_API_PREFIX`.

### Пример запроса
```bash
curl -X POST http://0.0.0.0:8000/api/v1/llm/test \
  -H "Content-Type: application/json" \
  -d '{"query":"ping"}'
```
Если префикс API настроен иначе, скорректируйте путь в примере (замените `/api/v1`).


Запуск:
1. Перейти в папку проекта
2. python -m venv .venv
3. Активировать виртуальное окружение
   .\.venv\Scripts\Activate.ps1
4. python -m pip install --upgrade pip setuptools
   python -m pip install -e .

5. запуск сервера:
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   Или воспользоваться точкой входа agent-service, которая вызывает app.main.main() и передаёт хост/порт из настроек:
   agent-service



сборка плагина:
1. .\gradlew.bat build
2. ide-plugin\gradlew.bat -p ide-plugin buildPlugin

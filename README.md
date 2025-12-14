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

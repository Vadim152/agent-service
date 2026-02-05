# OpenClaw — граф архитектуры (обзор)

Ниже — высокоуровневый граф архитектуры OpenClaw по результатам изучения исходников и README.

```mermaid
flowchart TD
    subgraph Inbound[Каналы и клиенты]
      WA[WhatsApp]
      TG[Telegram]
      SL[Slack/Discord/Signal/...]
      WEB[WebChat / Control UI]
      CLI[CLI openclaw]
      NODE[Mobile/Desktop Nodes]
    end

    subgraph Gateway[Gateway (единая control plane)]
      WS[WebSocket/HTTP сервер]
      AUTH[Auth + Pairing + Session policy]
      ROUTER[Маршрутизация событий/сообщений]
      METHODS[Gateway Methods API]
      PLUGINS[Plugin/Channel plugins]
      HOOKS[Hooks / Automation / Cron]
    end

    subgraph AgentCore[Agent Core]
      AGENT[Agent runtime / Pi agent]
      SKILLS[Skills registry (bundled/workspace/remote)]
      MEMORY[Sessions + Memory + Usage]
      TOOLS[Tooling: browser, canvas, node commands]
      MODELS[Model catalog + failover]
    end

    subgraph Infra[Infrastructure]
      CFG[Config + reload + migrations]
      OBS[Logging + diagnostics + health]
      REMOTE[Tailscale/Remote exposure]
      BIN[Binary/runtime guards]
    end

    WA --> WS
    TG --> WS
    SL --> WS
    WEB --> WS
    CLI --> WS
    NODE --> WS

    WS --> AUTH --> ROUTER
    ROUTER --> METHODS
    ROUTER --> PLUGINS
    ROUTER --> HOOKS

    METHODS --> AGENT
    PLUGINS --> AGENT
    HOOKS --> AGENT

    AGENT --> SKILLS
    AGENT --> MEMORY
    AGENT --> TOOLS
    AGENT --> MODELS

    CFG --> WS
    CFG --> AGENT
    OBS --> WS
    OBS --> AGENT
    REMOTE --> WS
    BIN --> AGENT
```

## Ключевые архитектурные идеи OpenClaw

1. **Единая control plane (Gateway)**: все каналы, UI, CLI и устройства входят через один серверный контур.
2. **Плагинность по каналам и capability**: каналы и методы расширяются без переписывания ядра.
3. **Чёткое разделение runtime-состояния**: конфиг, runtime-state, методы API и sidecar-сервисы разделены по модулям.
4. **Automation-first**: hooks/cron/webhooks встроены в архитектуру, а не добавлены постфактум.
5. **Наблюдаемость и безопасность как базовый слой**: auth/pairing, health, diagnostics, structured logging присутствуют в core-потоке.

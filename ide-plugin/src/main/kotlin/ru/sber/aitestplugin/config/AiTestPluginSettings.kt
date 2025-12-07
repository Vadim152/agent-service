package ru.sber.aitestplugin.config

/**
 * Хранит настройки доступа к backend-сервису agent-service.
 * В дальнейшем будет интегрирован с PersistentStateComponent для хранения между сессиями IDE.
 */
data class AiTestPluginSettings(
    var backendUrl: String = DEFAULT_BACKEND_URL,
    var requestTimeoutMs: Int = DEFAULT_TIMEOUT_MS
) {
    companion object {
        const val DEFAULT_BACKEND_URL: String = "http://localhost:8000/api/v1"
        const val DEFAULT_TIMEOUT_MS: Int = 30_000

        /**
         * Возвращает текущие настройки (пока заглушка, позже будет читать из state service).
         */
        fun current(): AiTestPluginSettings = AiTestPluginSettings()
    }
}

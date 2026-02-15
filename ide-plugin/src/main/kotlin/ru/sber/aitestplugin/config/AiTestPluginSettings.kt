package ru.sber.aitestplugin.config

/**
 * Хранит настройки доступа к backend-сервису agent-service.
 * В дальнейшем будет интегрирован с PersistentStateComponent для хранения между сессиями IDE.
 */
data class AiTestPluginSettings(
    var backendUrl: String = DEFAULT_BACKEND_URL,
    var requestTimeoutMs: Int = DEFAULT_TIMEOUT_MS,
    var chatSendTimeoutMs: Int = DEFAULT_CHAT_SEND_TIMEOUT_MS,
    var generateFeatureTimeoutMs: Int = DEFAULT_GENERATE_FEATURE_TIMEOUT_MS,
    var zephyrAuthType: ZephyrAuthType = ZephyrAuthType.TOKEN,
    var zephyrToken: String? = null,
    var zephyrLogin: String? = null,
    var zephyrPassword: String? = null,
    var zephyrJiraInstance: String = DEFAULT_ZEPHYR_JIRA_INSTANCE,
    var zephyrProjects: MutableList<String> = mutableListOf(),
    var scanProjectRoot: String? = null,
    var scanSearchDepth: Int = DEFAULT_SCAN_DEPTH,
    var scanFilePattern: String = DEFAULT_SCAN_PATTERN,
    var scanLanguage: String = DEFAULT_LANGUAGE,
    var generateFeatureTargetPath: String? = null,
    var generateFeatureCreateFile: Boolean = true,
    var generateFeatureOverwriteExisting: Boolean = false,
    var generateFeatureLanguage: String? = null,
    var applyFeatureTargetPath: String? = null,
    var applyFeatureCreateFile: Boolean = true,
    var applyFeatureOverwriteExisting: Boolean = false,
    var showScanSteps: Boolean = true,
    var showFoundSteps: Boolean = true,
    var showUnmappedSteps: Boolean = true
) {
    companion object {
        const val DEFAULT_BACKEND_URL: String = "http://localhost:8000/api/v1"
        const val DEFAULT_TIMEOUT_MS: Int = 30_000
        const val DEFAULT_CHAT_SEND_TIMEOUT_MS: Int = 120_000
        const val DEFAULT_GENERATE_FEATURE_TIMEOUT_MS: Int = 120_000
        const val DEFAULT_SCAN_DEPTH: Int = 5
        const val DEFAULT_SCAN_PATTERN: String = "**/*.feature"
        const val DEFAULT_LANGUAGE: String = "auto"
        const val DEFAULT_ZEPHYR_JIRA_INSTANCE: String = "Sigma"

        /**
         * Возвращает текущие настройки, сохранённые в PersistentStateComponent.
         */
        fun current(): AiTestPluginSettings = AiTestPluginSettingsService.getInstance().settings
    }
}

enum class ZephyrAuthType {
    TOKEN,
    LOGIN_PASSWORD
}

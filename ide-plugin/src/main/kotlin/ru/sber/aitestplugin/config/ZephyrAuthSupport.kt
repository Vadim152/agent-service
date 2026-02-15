package ru.sber.aitestplugin.config

import ru.sber.aitestplugin.model.ZephyrAuthDto

private val jiraInstanceOptions = mapOf(
    "Sigma" to "https://jira.sberbank.ru"
)

fun AiTestPluginSettings.zephyrAuthValidationError(): String? =
    when (zephyrAuthType) {
        ZephyrAuthType.TOKEN -> {
            val token = zephyrToken?.trim().orEmpty()
            if (token.isBlank()) {
                "Укажите токен Jira/Zephyr в настройках (Auth type: Token)."
            } else {
                null
            }
        }
        ZephyrAuthType.LOGIN_PASSWORD -> {
            val login = zephyrLogin?.trim().orEmpty()
            val password = zephyrPassword?.trim().orEmpty()
            if (login.isBlank() || password.isBlank()) {
                "Укажите логин и пароль Jira/Zephyr в настройках (Auth type: Login/Password)."
            } else {
                null
            }
        }
    }

fun AiTestPluginSettings.toZephyrAuthDto(): ZephyrAuthDto =
    ZephyrAuthDto(
        authType = zephyrAuthType,
        token = zephyrToken?.trim().orEmpty().ifBlank { null },
        login = zephyrLogin?.trim().orEmpty().ifBlank { null },
        password = zephyrPassword?.trim().orEmpty().ifBlank { null }
    )

fun AiTestPluginSettings.toZephyrAuthHeaders(): Map<String, String> {
    val headers = mutableMapOf<String, String>()
    headers["X-Zephyr-Auth-Type"] = zephyrAuthType.name
    when (zephyrAuthType) {
        ZephyrAuthType.TOKEN -> {
            zephyrToken?.trim()?.takeIf { it.isNotBlank() }?.let { headers["X-Zephyr-Token"] = it }
        }
        ZephyrAuthType.LOGIN_PASSWORD -> {
            zephyrLogin?.trim()?.takeIf { it.isNotBlank() }?.let { headers["X-Zephyr-Login"] = it }
            zephyrPassword?.trim()?.takeIf { it.isNotBlank() }?.let { headers["X-Zephyr-Password"] = it }
        }
    }
    return headers
}

fun resolveJiraInstanceUrl(raw: String?): String? {
    val value = raw?.trim().orEmpty()
    if (value.isBlank()) return null
    if (value.startsWith("http://") || value.startsWith("https://")) return value
    return jiraInstanceOptions[value]
}

fun resolveJiraInstanceLabel(raw: String?): String {
    val value = raw?.trim().orEmpty()
    if (value.isBlank()) return ""
    return jiraInstanceOptions.entries.firstOrNull { it.value == value }?.key ?: value
}

fun AiTestPluginSettings.toJiraInstanceUrl(): String? = resolveJiraInstanceUrl(zephyrJiraInstance)

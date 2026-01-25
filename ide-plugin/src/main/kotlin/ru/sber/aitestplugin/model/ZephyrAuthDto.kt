package ru.sber.aitestplugin.model

import ru.sber.aitestplugin.config.ZephyrAuthType

data class ZephyrAuthDto(
    val authType: ZephyrAuthType,
    val token: String? = null,
    val login: String? = null,
    val password: String? = null
)

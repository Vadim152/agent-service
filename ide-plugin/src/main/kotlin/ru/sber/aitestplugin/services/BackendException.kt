package ru.sber.aitestplugin.services

/**
 * Общее исключение для ошибок взаимодействия с backend agent-service.
 */
class BackendException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

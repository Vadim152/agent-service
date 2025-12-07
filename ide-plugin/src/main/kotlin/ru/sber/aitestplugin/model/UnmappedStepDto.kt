package ru.sber.aitestplugin.model

/**
 * Шаг тесткейса, для которого не найдено сопоставление.
 */
data class UnmappedStepDto(
    val text: String,
    val reason: String? = null
)

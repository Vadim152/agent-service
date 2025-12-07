package ru.sber.aitestplugin.model

/**
 * Упрощённое представление шага Cucumber для UI.
 */
data class StepDefinitionDto(
    val id: String,
    val keyword: String,
    val pattern: String,
    val codeRef: String,
    val tags: List<String>? = emptyList()
)

package ru.sber.aitestplugin.model

/**
 * Упрощённое представление шага Cucumber для UI.
 */
data class StepDefinitionDto(
    val id: String,
    val keyword: String,
    val pattern: String,
    val codeRef: String,
    val patternType: String? = null,
    val regex: String? = null,
    val parameters: List<StepParameterDto>? = emptyList(),
    val tags: List<String>? = emptyList(),
    val language: String? = null,
    val implementation: StepImplementationDto? = null,
    val summary: String? = null,
    val docSummary: String? = null,
    val examples: List<String>? = emptyList()
)

data class StepParameterDto(
    val name: String,
    val type: String? = null,
    val placeholder: String? = null
)

data class StepImplementationDto(
    val file: String? = null,
    val line: Int? = null,
    val className: String? = null,
    val methodName: String? = null
)

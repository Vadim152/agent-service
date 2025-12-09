package ru.sber.aitestplugin.model

import java.time.Instant

/** Запрос на сканирование шагов. */
data class ScanStepsRequestDto(
    val projectRoot: String
)

/** Ответ на сканирование шагов. */
data class ScanStepsResponseDto(
    val projectRoot: String,
    val stepsCount: Int,
    val updatedAt: Instant,
    val sampleSteps: List<StepDefinitionDto>? = emptyList(),
    val unmappedSteps: List<UnmappedStepDto> = emptyList()
)

package ru.sber.aitestplugin.model

import java.time.Instant

/** Р—Р°РїСЂРѕСЃ РЅР° СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ С€Р°РіРѕРІ. */
data class ScanStepsRequestDto(
    val projectRoot: String,
    val additionalRoots: List<String> = emptyList(),
    val providedSteps: List<StepDefinitionDto> = emptyList()
)

/** РћС‚РІРµС‚ РЅР° СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ С€Р°РіРѕРІ. */
data class ScanStepsResponseDto(
    val projectRoot: String,
    val stepsCount: Int,
    val updatedAt: Instant,
    val sampleSteps: List<StepDefinitionDto>? = emptyList(),
    val unmappedSteps: List<UnmappedStepDto> = emptyList()
)

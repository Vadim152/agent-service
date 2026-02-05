package ru.sber.aitestplugin.services

import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.JobCreateRequestDto
import ru.sber.aitestplugin.model.JobCreateResponseDto
import ru.sber.aitestplugin.model.JobStatusResponseDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto

/**
 * Абстракция клиента, обращающегося к backend-сервису agent-service.
 * Методы предполагают выполнение в фоновых задачах, чтобы не блокировать UI.
 */
interface BackendClient {
    fun scanSteps(projectRoot: String): ScanStepsResponseDto

    fun listSteps(projectRoot: String): List<StepDefinitionDto>

    fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto

    fun createJob(request: JobCreateRequestDto): JobCreateResponseDto

    fun getJob(jobId: String): JobStatusResponseDto

    fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto
}

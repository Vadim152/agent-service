package ru.sber.aitestplugin.services

import ru.sber.aitestplugin.config.AiTestPluginSettings
import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto

/**
 * Реализация BackendClient, использующая HTTP вызовы к агенту.
 * Пока оставлена как заглушка; реальный код будет использовать HTTP-клиент IntelliJ/Java.
 */
class HttpBackendClient(
    private val settingsProvider: () -> AiTestPluginSettings = { AiTestPluginSettings.current() }
) : BackendClient {

    override fun scanSteps(projectRoot: String): ScanStepsResponseDto {
        // TODO: отправить POST {backendUrl}/steps/scan-steps и десериализовать ответ
        throw BackendException("scanSteps is not implemented")
    }

    override fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto {
        // TODO: отправить POST {backendUrl}/feature/generate-feature и десериализовать ответ
        throw BackendException("generateFeature is not implemented")
    }

    override fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto {
        // TODO: отправить POST {backendUrl}/feature/apply-feature и десериализовать ответ
        throw BackendException("applyFeature is not implemented")
    }

    private fun baseUrl(): String = settingsProvider().backendUrl.trimEnd('/')
}

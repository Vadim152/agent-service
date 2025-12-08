package ru.sber.aitestplugin.services

import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.SerializationFeature
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import ru.sber.aitestplugin.config.AiTestPluginSettings
import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.ScanStepsRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * Реализация BackendClient, использующая HTTP вызовы к агенту.
 */
class HttpBackendClient(
    private val settingsProvider: () -> AiTestPluginSettings = { AiTestPluginSettings.current() }
) : BackendClient {

    private val mapper = jacksonObjectMapper()
        .registerModule(JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)

    override fun scanSteps(projectRoot: String): ScanStepsResponseDto {
        val request = ScanStepsRequestDto(projectRoot)
        return post("/steps/scan-steps", request)
    }

    override fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto =
        post("/feature/generate-feature", request)

    override fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto =
        post("/feature/apply-feature", request)

    private inline fun <reified T : Any> post(path: String, payload: Any): T {
        val settings = settingsProvider()
        val url = "${settings.backendUrl.trimEnd('/')}$path"
        val client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(settings.requestTimeoutMs.toLong()))
            .build()

        val body = mapper.writeValueAsString(payload)
        val request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofMillis(settings.requestTimeoutMs.toLong()))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()

        val response = try {
            client.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (ex: Exception) {
            throw BackendException("Failed to call $url: ${ex.message}", ex)
        }

        if (response.statusCode() !in 200..299) {
            val message = response.body().takeIf { it.isNotBlank() }
                ?: "HTTP ${response.statusCode()}"
            throw BackendException("Backend $url responded with ${response.statusCode()}: $message")
        }

        return try {
            mapper.readValue(response.body())
        } catch (ex: Exception) {
            throw BackendException("Failed to parse response from $url: ${ex.message}", ex)
        }
    }
}

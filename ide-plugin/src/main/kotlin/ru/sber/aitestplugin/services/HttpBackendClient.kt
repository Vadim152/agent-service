package ru.sber.aitestplugin.services

import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.SerializationFeature
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import com.intellij.openapi.diagnostic.Logger
import ru.sber.aitestplugin.config.AiTestPluginSettings
import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.ScanStepsRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import com.fasterxml.jackson.databind.JsonNode
import java.net.Proxy
import java.net.ProxySelector
import java.nio.charset.StandardCharsets
import java.time.Duration

/**
 * Реализация BackendClient, использующая HTTP вызовы к агенту.
 */
class HttpBackendClient(
    private val settingsProvider: () -> AiTestPluginSettings = { AiTestPluginSettings.current() }
) : BackendClient {

    private val logger = Logger.getInstance(HttpBackendClient::class.java)

    private val mapper = jacksonObjectMapper()
        .registerModule(JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)

    override fun scanSteps(projectRoot: String): ScanStepsResponseDto {
        val request = ScanStepsRequestDto(projectRoot)
        val encodedProjectRoot = URLEncoder.encode(projectRoot, StandardCharsets.UTF_8)
        return post("/steps/scan-steps?projectRoot=$encodedProjectRoot", request)
    }

    override fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto {
        val sanitizedRequest = request.copy(
            projectRoot = request.projectRoot.trim(),
            testCaseText = request.testCaseText.trim()
        )

        if (sanitizedRequest.projectRoot.isBlank()) {
            throw BackendException("Project root must not be empty")
        }

        if (sanitizedRequest.testCaseText.isBlank()) {
            throw BackendException("Test case text must not be empty")
        }

        return post("/feature/generate-feature", sanitizedRequest)
    }

    override fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto =
        post("/feature/apply-feature", request)

    private inline fun <reified T : Any> post(path: String, payload: Any): T {
        val settings = settingsProvider()
        val url = "${settings.backendUrl.trimEnd('/')}$path"
        val proxySelector = buildProxySelector(settings.backendUrl)
        val client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(settings.requestTimeoutMs.toLong()))
            .proxy(proxySelector)
            .build()

        val body = mapper.writeValueAsString(payload)
        val bodyBytes = body.toByteArray(StandardCharsets.UTF_8)
        val contentType = "application/json"
        val bodyLength = bodyBytes.size
        val request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(Duration.ofMillis(settings.requestTimeoutMs.toLong()))
            .header("Content-Type", contentType)
            .header("X-Body-Length", bodyLength.toString())
            // HttpClient automatically sets Content-Length when the BodyPublisher has a known size.
            // Adding the header manually triggers "restricted header name" errors in the IDE runtime.
            .POST(HttpRequest.BodyPublishers.ofByteArray(bodyBytes))
            .build()

        if (logger.isDebugEnabled) {
            val preview = body.take(500)
            logger.debug(
                "Sending POST to $url with Content-Type=$contentType, body size=$bodyLength bytes, preview=\"$preview\""
            )
        }

        val response = try {
            client.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (ex: Exception) {
            if (logger.isDebugEnabled) {
                logger.debug(
                    "Failed to send POST to $url with body size=${bodyBytes.size} bytes",
                    ex
                )
            }
            throw BackendException("Failed to call $url: ${ex.message}", ex)
        }

        if (response.statusCode() !in 200..299) {
            if (logger.isDebugEnabled) {
                logger.debug(
                    "Received non-2xx from $url: status=${response.statusCode()}, headers=${response.headers().map()}, body=\"${response.body()}\""
                )
            }
            val message = when (response.statusCode()) {
                422 -> {
                    if (logger.isDebugEnabled) {
                        logger.debug("Received 422 from $url for payload: $body")
                    }
                    parseValidationError(response.body())
                }
                else -> response.body().takeIf { it.isNotBlank() } ?: "HTTP ${response.statusCode()}"
            }
            throw BackendException("Backend $url responded with ${response.statusCode()}: $message")
        }

        return try {
            mapper.readValue(response.body())
        } catch (ex: Exception) {
            throw BackendException("Failed to parse response from $url: ${ex.message}", ex)
        }
    }

    private fun parseValidationError(body: String): String {
        if (body.isBlank()) return "Validation failed with empty response"

        return try {
            val root = mapper.readValue<JsonNode>(body)
            val detail = root.get("detail")
            when {
                detail == null -> body
                detail.isTextual -> detail.asText()
                detail.isArray -> detail.joinToString("; ") { node ->
                    val path = node.get("loc")?.joinToString(".") { it.asText() }
                    val message = node.get("msg")?.asText() ?: node.get("type")?.asText()
                    listOfNotNull(path, message).joinToString(": ")
                }.ifBlank { body }
                else -> detail.toString()
            }
        } catch (_: Exception) {
            body
        }
    }

    private fun buildProxySelector(backendUrl: String): ProxySelector {
        val backendHost = runCatching { URI.create(backendUrl).host }.getOrNull()
        val bypassHosts = setOf("localhost", "127.0.0.1", "::1") + listOfNotNull(backendHost)
        val defaultSelector = ProxySelector.getDefault()

        return object : ProxySelector() {
            override fun select(uri: URI?): List<Proxy> {
                val host = uri?.host?.lowercase()
                if (host != null && bypassHosts.any { it.equals(host, ignoreCase = true) }) {
                    return listOf(Proxy.NO_PROXY)
                }
                return defaultSelector?.select(uri) ?: listOf(Proxy.NO_PROXY)
            }

            override fun connectFailed(uri: URI?, sa: java.net.SocketAddress?, ioe: java.io.IOException?) {
                defaultSelector?.connectFailed(uri, sa, ioe)
            }
        }
    }
}

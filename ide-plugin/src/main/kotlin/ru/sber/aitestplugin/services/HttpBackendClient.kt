package ru.sber.aitestplugin.services

import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.SerializationFeature
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import com.intellij.openapi.diagnostic.Logger
import ru.sber.aitestplugin.config.AiTestPluginSettings
import ru.sber.aitestplugin.config.toZephyrAuthDto
import ru.sber.aitestplugin.config.toZephyrAuthHeaders
import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatCommandRequestDto
import ru.sber.aitestplugin.model.ChatCommandResponseDto
import ru.sber.aitestplugin.model.ChatMessageAcceptedResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatSessionCreateResponseDto
import ru.sber.aitestplugin.model.ChatSessionDiffResponseDto
import ru.sber.aitestplugin.model.ChatSessionsListResponseDto
import ru.sber.aitestplugin.model.ChatSessionStatusResponseDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.ChatToolDecisionResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.JobCreateRequestDto
import ru.sber.aitestplugin.model.JobCreateResponseDto
import ru.sber.aitestplugin.model.JobResultResponseDto
import ru.sber.aitestplugin.model.JobStatusResponseDto
import ru.sber.aitestplugin.model.ScanStepsRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import java.net.URI
import java.net.URLEncoder
import com.fasterxml.jackson.databind.JsonNode
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.ConcurrentHashMap

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
    private val clientsByTimeoutMs = ConcurrentHashMap<Int, OkHttpClient>()

    override fun scanSteps(projectRoot: String): ScanStepsResponseDto {
        val request = ScanStepsRequestDto(projectRoot)
        val encodedProjectRoot = URLEncoder.encode(projectRoot, StandardCharsets.UTF_8)
        return post("/steps/scan-steps?projectRoot=$encodedProjectRoot", request)
    }

    override fun listSteps(projectRoot: String): List<StepDefinitionDto> {
        val encodedProjectRoot = URLEncoder.encode(projectRoot, StandardCharsets.UTF_8)
        return get("/steps/?projectRoot=$encodedProjectRoot")
    }

    override fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto {
        val settings = settingsProvider()
        val zephyrAuth = settings.toZephyrAuthDto()
        val sanitizedRequest = request.copy(
            projectRoot = request.projectRoot.trim(),
            testCaseText = request.testCaseText.trim(),
            zephyrAuth = request.zephyrAuth ?: zephyrAuth
        )

        if (sanitizedRequest.projectRoot.isBlank()) {
            throw BackendException("Project root must not be empty")
        }

        if (sanitizedRequest.testCaseText.isBlank()) {
            throw BackendException("Test case text must not be empty")
        }

        return post(
            "/feature/generate-feature",
            sanitizedRequest,
            timeoutMs = settings.generateFeatureTimeoutMs,
            headers = settings.toZephyrAuthHeaders()
        )
    }

    override fun createJob(request: JobCreateRequestDto): JobCreateResponseDto =
        post("/jobs", request)

    override fun getJob(jobId: String): JobStatusResponseDto =
        get("/jobs/$jobId")

    override fun getJobResult(jobId: String): JobResultResponseDto =
        get("/jobs/$jobId/result")

    override fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto =
        post("/feature/apply-feature", request)

    override fun createChatSession(request: ChatSessionCreateRequestDto): ChatSessionCreateResponseDto =
        post("/chat/sessions", request)

    override fun listChatSessions(projectRoot: String, limit: Int): ChatSessionsListResponseDto {
        val encodedProjectRoot = URLEncoder.encode(projectRoot, StandardCharsets.UTF_8)
        val boundedLimit = limit.coerceIn(1, 200)
        return get("/chat/sessions?projectRoot=$encodedProjectRoot&limit=$boundedLimit")
    }

    override fun sendChatMessage(sessionId: String, request: ChatMessageRequestDto): ChatMessageAcceptedResponseDto =
        post("/chat/sessions/$sessionId/messages", request)

    override fun getChatHistory(sessionId: String): ChatHistoryResponseDto =
        get("/chat/sessions/$sessionId/history")

    override fun getChatStatus(sessionId: String): ChatSessionStatusResponseDto =
        get("/chat/sessions/$sessionId/status")

    override fun getChatDiff(sessionId: String): ChatSessionDiffResponseDto =
        get("/chat/sessions/$sessionId/diff")

    override fun executeChatCommand(
        sessionId: String,
        request: ChatCommandRequestDto
    ): ChatCommandResponseDto = post("/chat/sessions/$sessionId/commands", request)

    override fun submitChatToolDecision(
        sessionId: String,
        request: ChatToolDecisionRequestDto
    ): ChatToolDecisionResponseDto = post("/chat/sessions/$sessionId/tool-decisions", request)

    private inline fun <reified T : Any> post(
        path: String,
        payload: Any,
        timeoutMs: Int? = null,
        headers: Map<String, String> = emptyMap()
    ): T {
        val settings = settingsProvider()
        val url = "${settings.backendUrl.trimEnd('/')}$path"
        val effectiveTimeoutMs = timeoutMs ?: settings.requestTimeoutMs
        val client = getHttpClient(effectiveTimeoutMs)

        val body = mapper.writeValueAsString(payload)
        val bodyBytes = body.toByteArray(StandardCharsets.UTF_8)
        val contentType = "application/json"
        val bodyLength = bodyBytes.size
        val requestBody = bodyBytes.toRequestBody(contentType.toMediaType())
        val requestBuilder = Request.Builder()
            .url(URI.create(url).toURL())
            .header("Content-Type", contentType)
            .header("X-Body-Length", bodyLength.toString())
            .post(requestBody)
        headers.forEach { (key, value) ->
            requestBuilder.header(key, value)
        }
        val request = requestBuilder.build()

        if (logger.isDebugEnabled) {
            val preview = body.take(500)
            logger.debug(
                "Sending POST to $url with Content-Type=$contentType, body size=$bodyLength bytes, preview=\"$preview\""
            )
        }

        val response = try {
            client.newCall(request).execute()
        } catch (ex: Exception) {
            if (logger.isDebugEnabled) {
                logger.debug(
                    "Failed to send POST to $url with body size=${bodyBytes.size} bytes",
                    ex
                )
            }
            throw BackendException("Failed to call $url: ${ex.message}", ex)
        }

        response.use { httpResponse ->
            val responseBody = httpResponse.body?.string().orEmpty()
            if (!httpResponse.isSuccessful) {
                if (logger.isDebugEnabled) {
                    logger.debug(
                        "Received non-2xx from $url: status=${httpResponse.code}, headers=${httpResponse.headers}, body=\"$responseBody\""
                    )
                }
                val message = when (httpResponse.code) {
                    422 -> {
                        if (logger.isDebugEnabled) {
                            logger.debug("Received 422 from $url for payload: $body")
                        }
                        parseValidationError(responseBody)
                    }
                    else -> responseBody.takeIf { it.isNotBlank() } ?: "HTTP ${httpResponse.code}"
                }
                throw BackendException("Backend $url responded with ${httpResponse.code}: $message")
            }

            return try {
                mapper.readValue(responseBody)
            } catch (ex: Exception) {
                throw BackendException("Failed to parse response from $url: ${ex.message}", ex)
            }
        }
    }

    private inline fun <reified T : Any> get(
        path: String,
        timeoutMs: Int? = null
    ): T {
        val settings = settingsProvider()
        val url = "${settings.backendUrl.trimEnd('/')}$path"
        val effectiveTimeoutMs = timeoutMs ?: settings.requestTimeoutMs
        val client = getHttpClient(effectiveTimeoutMs)

        val request = Request.Builder()
            .url(URI.create(url).toURL())
            .get()
            .build()

        val response = try {
            client.newCall(request).execute()
        } catch (ex: Exception) {
            if (logger.isDebugEnabled) {
                logger.debug("Failed to send GET to $url", ex)
            }
            throw BackendException("Failed to call $url: ${ex.message}", ex)
        }

        response.use { httpResponse ->
            val responseBody = httpResponse.body?.string().orEmpty()
            if (!httpResponse.isSuccessful) {
                if (logger.isDebugEnabled) {
                    logger.debug(
                        "Received non-2xx from $url: status=${httpResponse.code}, headers=${httpResponse.headers}, body=\"$responseBody\""
                    )
                }
                val message = responseBody.takeIf { it.isNotBlank() } ?: "HTTP ${httpResponse.code}"
                throw BackendException("Backend $url responded with ${httpResponse.code}: $message")
            }

            return try {
                mapper.readValue(responseBody)
            } catch (ex: Exception) {
                throw BackendException("Failed to parse response from $url: ${ex.message}", ex)
            }
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

    private fun getHttpClient(timeoutMs: Int): OkHttpClient {
        val boundedTimeout = timeoutMs.coerceAtLeast(1)
        return clientsByTimeoutMs.computeIfAbsent(boundedTimeout) { timeout ->
            val duration = Duration.ofMillis(timeout.toLong())
            OkHttpClient.Builder()
                .callTimeout(duration)
                .connectTimeout(duration)
                .readTimeout(duration)
                .build()
        }
    }
}

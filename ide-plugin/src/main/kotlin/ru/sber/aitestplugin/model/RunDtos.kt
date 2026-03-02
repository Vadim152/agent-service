package ru.sber.aitestplugin.model

import java.time.Instant

data class RunCreateRequestDto(
    val projectRoot: String,
    val plugin: String,
    val input: Map<String, Any?> = emptyMap(),
    val sessionId: String? = null,
    val profile: String = "quick",
    val source: String = "ide-plugin",
    val priority: String = "normal"
)

data class RunCreateResponseDto(
    val runId: String,
    val status: String,
    val sessionId: String? = null,
    val plugin: String
)

data class RunStatusResponseDto(
    val runId: String,
    val sessionId: String? = null,
    val plugin: String,
    val status: String,
    val source: String? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null
)

data class RunResultResponseDto(
    val runId: String,
    val sessionId: String? = null,
    val plugin: String,
    val status: String,
    val source: String? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null,
    val output: FeatureResultDto? = null,
    val attempts: List<RunAttemptDto> = emptyList()
)

data class RunEventResponseDto(
    val eventType: String,
    val payload: Map<String, Any?> = emptyMap(),
    val createdAt: Instant,
    val index: Int
)

data class RunAttemptDto(
    val attemptId: String,
    val status: String,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null,
    val classification: Map<String, Any?>? = null,
    val remediation: Map<String, Any?>? = null,
    val artifacts: Map<String, String> = emptyMap()
)

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
    val runtime: String? = null,
    val backend: String? = null,
    val status: String,
    val source: String? = null,
    val backendRunId: String? = null,
    val backendSessionId: String? = null,
    val lastSyncedAt: Instant? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null
)

data class RunResultResponseDto(
    val runId: String,
    val sessionId: String? = null,
    val plugin: String,
    val runtime: String? = null,
    val backend: String? = null,
    val status: String,
    val source: String? = null,
    val backendRunId: String? = null,
    val backendSessionId: String? = null,
    val lastSyncedAt: Instant? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null,
    val output: FeatureResultDto? = null,
    val attempts: List<RunAttemptDto> = emptyList()
)

data class RunArtifactDto(
    val artifactId: String? = null,
    val name: String,
    val uri: String,
    val attemptId: String? = null,
    val mediaType: String? = null,
    val size: Int? = null,
    val checksum: String? = null,
    val connectorSource: String? = null,
    val storageBackend: String? = null,
    val storagePath: String? = null,
    val storageBucket: String? = null,
    val storageKey: String? = null,
    val signedUrl: String? = null,
    val content: String? = null
)

data class RunArtifactsResponseDto(
    val runId: String,
    val items: List<RunArtifactDto> = emptyList()
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

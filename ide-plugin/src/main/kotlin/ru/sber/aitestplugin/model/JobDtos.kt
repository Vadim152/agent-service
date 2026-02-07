package ru.sber.aitestplugin.model

import java.time.Instant

data class JobCreateRequestDto(
    val projectRoot: String,
    val testCaseText: String,
    val targetPath: String? = null,
    val profile: String = "quick",
    val createFile: Boolean = false,
    val overwriteExisting: Boolean = false,
    val language: String? = null,
    val source: String = "ide-plugin"
)

data class JobCreateResponseDto(
    val jobId: String,
    val status: String
)

data class JobStatusResponseDto(
    val jobId: String,
    val runId: String? = null,
    val status: String,
    val source: String? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null
)

data class JobAttemptsResponseDto(
    val jobId: String,
    val runId: String? = null,
    val attempts: List<JobAttemptDto> = emptyList()
)

data class JobAttemptDto(
    val attemptId: String,
    val status: String,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null,
    val classification: Map<String, Any?>? = null,
    val remediation: Map<String, Any?>? = null,
    val artifacts: Map<String, String> = emptyMap()
)

data class JobFeatureResultDto(
    val featureText: String = "",
    val unmappedSteps: List<UnmappedStepDto> = emptyList(),
    val unmapped: List<String> = emptyList(),
    val usedSteps: List<StepDefinitionDto> = emptyList(),
    val buildStage: String? = null,
    val stepsSummary: StepsSummaryDto? = null,
    val meta: Map<String, Any?>? = null,
    val pipeline: List<Map<String, Any?>> = emptyList(),
    val fileStatus: Map<String, Any?>? = null
)

data class StepsSummaryDto(
    val exact: Int = 0,
    val fuzzy: Int = 0,
    val unmatched: Int = 0
)

data class JobResultResponseDto(
    val jobId: String,
    val runId: String? = null,
    val status: String,
    val source: String? = null,
    val incidentUri: String? = null,
    val startedAt: Instant? = null,
    val finishedAt: Instant? = null,
    val feature: JobFeatureResultDto? = null,
    val attempts: List<JobAttemptDto> = emptyList()
)

data class JobEventResponseDto(
    val eventType: String,
    val payload: Map<String, Any?> = emptyMap(),
    val createdAt: Instant,
    val index: Int
)

package ru.sber.aitestplugin.model

import java.time.Instant

data class OpenCodeCommandDto(
    val name: String,
    val description: String? = null,
    val source: String? = null,
    val template: String? = null,
    val subtask: Boolean = false,
    val hints: List<String> = emptyList(),
    val raw: Map<String, Any?> = emptyMap(),
    val alias: Boolean = false,
    val hidden: Boolean = false,
    val nativeAction: String? = null
)

data class OpenCodeCommandsResponseDto(
    val items: List<OpenCodeCommandDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeCommandExecutionRequestDto(
    val sessionId: String? = null,
    val projectRoot: String? = null,
    val arguments: List<String> = emptyList(),
    val rawInput: String? = null,
    val messageMetadata: Map<String, Any?> = emptyMap()
)

data class OpenCodeCommandExecutionResponseDto(
    val commandId: String,
    val accepted: Boolean = true,
    val kind: String,
    val sessionId: String? = null,
    val runId: String? = null,
    val nativeAction: String? = null,
    val message: String? = null,
    val result: Map<String, Any?> = emptyMap(),
    val updatedAt: Instant
)

data class OpenCodeAgentDto(
    val name: String,
    val description: String? = null,
    val mode: String? = null,
    val native: Boolean = false,
    val permissionCount: Int = 0,
    val raw: Map<String, Any?> = emptyMap()
)

data class OpenCodeAgentsResponseDto(
    val items: List<OpenCodeAgentDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeMcpDto(
    val name: String,
    val enabled: Boolean = true,
    val transport: String? = null,
    val description: String? = null,
    val raw: Map<String, Any?> = emptyMap()
)

data class OpenCodeMcpsResponseDto(
    val items: List<OpenCodeMcpDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeProviderDto(
    val providerId: String,
    val name: String,
    val modelCount: Int = 0,
    val defaultModelId: String? = null,
    val raw: Map<String, Any?> = emptyMap()
)

data class OpenCodeProvidersResponseDto(
    val items: List<OpenCodeProviderDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeModelDto(
    val id: String,
    val providerId: String,
    val name: String,
    val status: String = "active",
    val limit: Map<String, Any?> = emptyMap(),
    val capabilities: Map<String, Any?> = emptyMap(),
    val raw: Map<String, Any?> = emptyMap()
)

data class OpenCodeModelsResponseDto(
    val items: List<OpenCodeModelDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeToolDto(
    val id: String,
    val name: String,
    val description: String? = null,
    val raw: Map<String, Any?> = emptyMap()
)

data class OpenCodeToolsResponseDto(
    val items: List<OpenCodeToolDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeResourceEntryDto(
    val kind: String,
    val name: String,
    val path: String,
    val entryType: String,
    val description: String? = null,
    val sourceRoot: String,
    val metadata: Map<String, Any?> = emptyMap()
)

data class OpenCodeResourcesResponseDto(
    val kind: String,
    val items: List<OpenCodeResourceEntryDto> = emptyList(),
    val total: Int = 0,
    val updatedAt: Instant
)

data class OpenCodeConfigSnapshotDto(
    val activeProjectRoot: String? = null,
    val activeConfigFile: String? = null,
    val activeConfigDir: String? = null,
    val resolvedProviders: List<String> = emptyList(),
    val resolvedModel: String? = null,
    val rawConfig: Map<String, Any?>? = null,
    val configError: String? = null,
    val serverRunning: Boolean = false,
    val serverReady: Boolean = false,
    val baseUrl: String = ""
)

data class OpenCodeCommandCatalogSummaryDto(
    val total: Int = 0,
    val names: List<String> = emptyList(),
    val updatedAt: Instant? = null
)

data class OpenCodeSessionEventDto(
    val eventType: String,
    val payload: Map<String, Any?> = emptyMap(),
    val createdAt: Instant,
    val index: Int
)

data class OpenCodeSessionEventsResponseDto(
    val sessionId: String,
    val items: List<OpenCodeSessionEventDto> = emptyList(),
    val nextCursor: Int,
    val hasMore: Boolean = false,
    val updatedAt: Instant
)

data class OpenCodeSessionStatusDto(
    val sessionId: String,
    val runtime: String = "opencode",
    val activity: String,
    val currentAction: String,
    val lastEventAt: Instant,
    val updatedAt: Instant,
    val pendingPermissionsCount: Int = 0,
    val activeRunId: String? = null,
    val activeRunStatus: String? = null,
    val activeRunBackend: String? = null,
    val backendSessionId: String? = null,
    val agentId: String? = null,
    val providerId: String? = null,
    val modelId: String? = null,
    val mcpCount: Int = 0,
    val commandCatalog: OpenCodeCommandCatalogSummaryDto = OpenCodeCommandCatalogSummaryDto(),
    val config: OpenCodeConfigSnapshotDto = OpenCodeConfigSnapshotDto(),
    val totals: ChatUsageTotalsDto = ChatUsageTotalsDto(),
    val limits: ChatLimitsDto = ChatLimitsDto(),
    val diffSummary: ChatDiffSummaryDto = ChatDiffSummaryDto(),
    val diffFiles: List<ChatDiffFileDto> = emptyList()
)

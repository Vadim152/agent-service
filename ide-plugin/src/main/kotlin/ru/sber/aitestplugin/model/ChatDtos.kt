package ru.sber.aitestplugin.model

import java.time.Instant

data class ChatSessionCreateRequestDto(
    val projectRoot: String,
    val source: String = "ide-plugin",
    val profile: String = "quick",
    val reuseExisting: Boolean = false
)

data class ChatSessionCreateResponseDto(
    val sessionId: String,
    val createdAt: Instant,
    val reused: Boolean = false,
    val memorySnapshot: Map<String, Any?> = emptyMap()
)

data class ChatSessionListItemDto(
    val sessionId: String,
    val projectRoot: String,
    val source: String = "ide-plugin",
    val profile: String = "quick",
    val status: String = "active",
    val activity: String = "idle",
    val currentAction: String = "Idle",
    val createdAt: Instant,
    val updatedAt: Instant,
    val lastMessagePreview: String? = null,
    val pendingPermissionsCount: Int = 0
)

data class ChatSessionsListResponseDto(
    val items: List<ChatSessionListItemDto> = emptyList(),
    val total: Int = 0
)

data class ChatMessageRequestDto(
    val messageId: String? = null,
    val role: String = "user",
    val content: String,
    val attachments: List<Map<String, Any?>> = emptyList()
)

data class ChatMessageAcceptedResponseDto(
    val sessionId: String,
    val runId: String,
    val accepted: Boolean = true
)

data class ChatToolDecisionRequestDto(
    val permissionId: String,
    val decision: String
)

data class ChatToolDecisionResponseDto(
    val sessionId: String,
    val runId: String,
    val accepted: Boolean = true
)

data class ChatMessageDto(
    val messageId: String,
    val role: String,
    val content: String,
    val runId: String? = null,
    val metadata: Map<String, Any?> = emptyMap(),
    val createdAt: Instant
)

data class ChatEventDto(
    val eventType: String,
    val payload: Map<String, Any?> = emptyMap(),
    val createdAt: Instant,
    val index: Int
)

data class ChatPendingPermissionDto(
    val permissionId: String,
    val title: String,
    val kind: String,
    val callId: String? = null,
    val messageId: String? = null,
    val metadata: Map<String, Any?> = emptyMap(),
    val createdAt: Instant
)

data class ChatHistoryResponseDto(
    val sessionId: String,
    val projectRoot: String,
    val source: String,
    val profile: String,
    val status: String,
    val messages: List<ChatMessageDto> = emptyList(),
    val events: List<ChatEventDto> = emptyList(),
    val pendingPermissions: List<ChatPendingPermissionDto> = emptyList(),
    val memorySnapshot: Map<String, Any?> = emptyMap(),
    val updatedAt: Instant
)

data class ChatTokenTotalsDto(
    val input: Int = 0,
    val output: Int = 0,
    val reasoning: Int = 0,
    val cacheRead: Int = 0,
    val cacheWrite: Int = 0
)

data class ChatUsageTotalsDto(
    val tokens: ChatTokenTotalsDto = ChatTokenTotalsDto(),
    val cost: Double = 0.0
)

data class ChatLimitsDto(
    val contextWindow: Int? = null,
    val used: Int = 0,
    val percent: Double? = null
)

data class ChatRiskDto(
    val level: String,
    val reasons: List<String> = emptyList()
)

data class ChatSessionStatusResponseDto(
    val sessionId: String,
    val activity: String,
    val currentAction: String,
    val lastEventAt: Instant,
    val updatedAt: Instant,
    val pendingPermissionsCount: Int,
    val totals: ChatUsageTotalsDto = ChatUsageTotalsDto(),
    val limits: ChatLimitsDto = ChatLimitsDto(),
    val lastRetryMessage: String? = null,
    val lastRetryAttempt: Int? = null,
    val lastRetryAt: Instant? = null,
    val risk: ChatRiskDto
)

data class ChatDiffSummaryDto(
    val files: Int = 0,
    val additions: Int = 0,
    val deletions: Int = 0
)

data class ChatDiffFileDto(
    val file: String,
    val additions: Int = 0,
    val deletions: Int = 0,
    val before: String = "",
    val after: String = ""
)

data class ChatSessionDiffResponseDto(
    val sessionId: String,
    val summary: ChatDiffSummaryDto = ChatDiffSummaryDto(),
    val files: List<ChatDiffFileDto> = emptyList(),
    val updatedAt: Instant,
    val risk: ChatRiskDto
)

data class ChatCommandRequestDto(
    val command: String
)

data class ChatCommandResponseDto(
    val sessionId: String,
    val command: String,
    val accepted: Boolean = true,
    val result: Map<String, Any?> = emptyMap(),
    val updatedAt: Instant,
    val risk: ChatRiskDto
)

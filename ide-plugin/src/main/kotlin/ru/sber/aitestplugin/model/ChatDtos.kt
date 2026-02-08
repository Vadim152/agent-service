package ru.sber.aitestplugin.model

import java.time.Instant

data class ChatSessionCreateRequestDto(
    val projectRoot: String,
    val source: String = "ide-plugin",
    val profile: String = "quick",
    val reuseExisting: Boolean = true
)

data class ChatSessionCreateResponseDto(
    val sessionId: String,
    val createdAt: Instant,
    val reused: Boolean = false,
    val memorySnapshot: Map<String, Any?> = emptyMap()
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
    val toolCallId: String,
    val decision: String,
    val editedArgs: Map<String, Any?>? = null
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

data class ChatPendingToolCallDto(
    val toolCallId: String,
    val toolName: String,
    val args: Map<String, Any?> = emptyMap(),
    val riskLevel: String,
    val requiresConfirmation: Boolean,
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
    val pendingToolCalls: List<ChatPendingToolCallDto> = emptyList(),
    val memorySnapshot: Map<String, Any?> = emptyMap(),
    val updatedAt: Instant
)


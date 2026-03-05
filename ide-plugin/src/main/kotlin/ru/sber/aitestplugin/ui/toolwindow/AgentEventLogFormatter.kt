package ru.sber.aitestplugin.ui.toolwindow

import ru.sber.aitestplugin.model.ChatEventDto
import java.time.Instant

internal object AgentEventLogFormatter {
    internal enum class TimelineKind {
        USER,
        AGENT_EVENT,
        ASSISTANT,
        SYSTEM
    }

    internal data class TimelineItem(
        val kind: TimelineKind,
        val text: String,
        val createdAt: Instant,
        val stableKey: String
    )

    private enum class EventCategory(val title: String) {
        STATUS("Status"),
        STEP("Step"),
        CHANGE("Change"),
        COMMAND("Command"),
        APPROVAL("Approval")
    }

    fun buildAgentEventLines(events: List<ChatEventDto>, maxLines: Int): List<TimelineItem> {
        val compact = events
            .sortedWith(compareBy<ChatEventDto> { it.createdAt }.thenBy { it.index })
            .mapNotNull { toEventLine(it) }
            .fold(mutableListOf<CompactEvent>()) { acc, line ->
                val previous = acc.lastOrNull()
                if (previous != null && previous.category == line.category && previous.title == line.title) {
                    acc[acc.lastIndex] = previous.copy(count = previous.count + 1)
                } else {
                    acc.add(line)
                }
                acc
            }
            .takeLast(maxLines)
        return compact.map { compactLine ->
            val title = if (compactLine.count > 1) "${compactLine.title} (x${compactLine.count})" else compactLine.title
            TimelineItem(
                kind = TimelineKind.AGENT_EVENT,
                text = "[${compactLine.category.title}] $title",
                createdAt = compactLine.createdAt,
                stableKey = compactLine.stableKey
            )
        }
    }

    fun mergeConversationAndEvents(messages: List<TimelineItem>, events: List<TimelineItem>): List<TimelineItem> =
        (messages + events).sortedWith(
            compareBy<TimelineItem> { it.createdAt }
                .thenBy { orderWeight(it.kind) }
                .thenBy { it.stableKey }
        )

    private fun orderWeight(kind: TimelineKind): Int = when (kind) {
        TimelineKind.USER -> 0
        TimelineKind.AGENT_EVENT -> 1
        TimelineKind.ASSISTANT -> 2
        TimelineKind.SYSTEM -> 3
    }

    private fun toEventLine(event: ChatEventDto): CompactEvent? {
        val normalized = event.eventType.lowercase()
        val detail = resolveDetail(event.payload)
        return when (normalized) {
            "heartbeat" -> null
            "message.received" -> compact(EventCategory.STATUS, "Request accepted", event)
            "opencode.run_created" -> compact(EventCategory.STATUS, "Run created", event)
            "opencode.run.queued" -> compact(EventCategory.STATUS, "Queued", event)
            "opencode.run.started" -> compact(EventCategory.STATUS, "Run started", event)
            "opencode.run.retrying" -> compact(EventCategory.STATUS, "Retrying run", event)
            "opencode.run.awaiting_approval", "permission.requested" ->
                compact(EventCategory.APPROVAL, "Approval required", event)
            "approval.decision", "permission.approved", "permission.rejected" ->
                compact(EventCategory.APPROVAL, "Approval decision sent", event)
            "opencode.run.artifact_published" ->
                compact(EventCategory.CHANGE, artifactMessage(event.payload), event)
            "command.executed", "opencode.command.executed" ->
                compact(EventCategory.COMMAND, commandMessage(event.payload), event)
            "opencode.run.progress" ->
                compact(EventCategory.STEP, if (detail.isNotBlank()) detail else "Working", event)
            "opencode.run.finished", "run.succeeded" -> null
            "opencode.run.failed", "run.failed" ->
                compact(EventCategory.STATUS, if (detail.isNotBlank()) "Failed: $detail" else "Failed", event)
            "run.cancelled", "opencode.run.cancelled" ->
                compact(EventCategory.STATUS, "Cancelled", event)
            else -> null
        }
    }

    private fun compact(category: EventCategory, title: String, event: ChatEventDto): CompactEvent = CompactEvent(
        category = category,
        title = title,
        createdAt = event.createdAt,
        stableKey = "trace:${event.index}:${event.eventType}"
    )

    private fun artifactMessage(payload: Map<String, Any?>): String {
        val artifact = payload["artifact"] as? Map<*, *>
        val artifactName = artifact?.get("name")?.toString()?.trim().orEmpty()
        return if (artifactName.isNotBlank()) "Updated $artifactName" else "Published changes"
    }

    private fun commandMessage(payload: Map<String, Any?>): String {
        val command = payload["command"]?.toString()?.trim().orEmpty()
        return if (command.isNotBlank()) "/$command" else "Tool command executed"
    }

    private fun resolveDetail(payload: Map<String, Any?>): String {
        val message = payload["message"]?.toString()?.trim().orEmpty()
        val currentAction = payload["currentAction"]?.toString()?.trim().orEmpty()
        val nestedPayload = payload["payload"] as? Map<*, *>
        val nestedType = nestedPayload?.get("type")?.toString()?.trim().orEmpty()
        val nestedInfo = nestedPayload?.get("info") as? Map<*, *>
        val nestedError = nestedInfo?.get("error") as? Map<*, *>
        val nestedErrorData = nestedError?.get("data") as? Map<*, *>
        val nestedErrorMessage = nestedErrorData?.get("message")?.toString()?.trim().orEmpty()
        return when {
            nestedErrorMessage.isNotBlank() -> nestedErrorMessage
            message.isNotBlank() -> message
            currentAction.isNotBlank() -> currentAction
            else -> nestedType
        }
    }

    private data class CompactEvent(
        val category: EventCategory,
        val title: String,
        val createdAt: Instant,
        val stableKey: String,
        val count: Int = 1
    )
}

package ru.sber.aitestplugin.ui.toolwindow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import ru.sber.aitestplugin.model.ChatEventDto
import java.time.Instant

class AgentEventLogFormatterTest {

    @Test
    fun `buildAgentEventLines maps categories and hides terminal success`() {
        val now = Instant.parse("2026-03-05T10:00:00Z")
        val events = listOf(
            ChatEventDto("opencode.run.started", emptyMap(), now, 0),
            ChatEventDto("opencode.run.progress", mapOf("currentAction" to "Scanning files"), now.plusSeconds(1), 1),
            ChatEventDto("opencode.run.artifact_published", mapOf("artifact" to mapOf("name" to "session-diff.json")), now.plusSeconds(2), 2),
            ChatEventDto("command.executed", mapOf("command" to "diff"), now.plusSeconds(3), 3),
            ChatEventDto("permission.requested", emptyMap(), now.plusSeconds(4), 4),
            ChatEventDto("run.succeeded", emptyMap(), now.plusSeconds(5), 5),
        )

        val lines = AgentEventLogFormatter.buildAgentEventLines(events, maxLines = 20)
        val text = lines.map { it.text }

        assertTrue(text.any { it.startsWith("[Status] Run started") })
        assertTrue(text.any { it.startsWith("[Step] Scanning files") })
        assertTrue(text.any { it.startsWith("[Change] Updated session-diff.json") })
        assertTrue(text.any { it.startsWith("[Command] /diff") })
        assertTrue(text.any { it.startsWith("[Approval] Approval required") })
        assertTrue(text.none { it.contains("succeeded", ignoreCase = true) })
    }

    @Test
    fun `buildAgentEventLines compacts repeated events`() {
        val now = Instant.parse("2026-03-05T10:00:00Z")
        val events = listOf(
            ChatEventDto("opencode.run.progress", mapOf("currentAction" to "Reading project"), now, 0),
            ChatEventDto("opencode.run.progress", mapOf("currentAction" to "Reading project"), now.plusSeconds(1), 1),
        )

        val lines = AgentEventLogFormatter.buildAgentEventLines(events, maxLines = 20)

        assertEquals(1, lines.size)
        assertEquals("[Step] Reading project (x2)", lines[0].text)
    }

    @Test
    fun `mergeConversationAndEvents puts event between user and assistant on same time`() {
        val now = Instant.parse("2026-03-05T10:00:00Z")
        val messages = listOf(
            AgentEventLogFormatter.TimelineItem(
                kind = AgentEventLogFormatter.TimelineKind.USER,
                text = "Please run agent",
                createdAt = now,
                stableKey = "m-user"
            ),
            AgentEventLogFormatter.TimelineItem(
                kind = AgentEventLogFormatter.TimelineKind.ASSISTANT,
                text = "Done",
                createdAt = now,
                stableKey = "m-assistant"
            )
        )
        val events = listOf(
            AgentEventLogFormatter.TimelineItem(
                kind = AgentEventLogFormatter.TimelineKind.AGENT_EVENT,
                text = "[Status] Run started",
                createdAt = now,
                stableKey = "e-1"
            )
        )

        val merged = AgentEventLogFormatter.mergeConversationAndEvents(messages, events)

        assertEquals(
            listOf(
                AgentEventLogFormatter.TimelineKind.USER,
                AgentEventLogFormatter.TimelineKind.AGENT_EVENT,
                AgentEventLogFormatter.TimelineKind.ASSISTANT
            ),
            merged.map { it.kind }
        )
    }
}

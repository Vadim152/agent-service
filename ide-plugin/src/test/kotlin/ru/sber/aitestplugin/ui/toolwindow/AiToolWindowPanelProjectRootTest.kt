package ru.sber.aitestplugin.ui.toolwindow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import ru.sber.aitestplugin.model.ChatMessageDto
import java.time.Instant

class AiToolWindowPanelProjectRootTest {

    @Test
    fun `opencode runtime uses ide base path`() {
        val result = resolveRuntimeProjectRootValue(
            runtime = "opencode",
            projectBasePath = "C:/repo/current-project"
        )

        assertEquals("C:/repo/current-project", result)
    }

    @Test
    fun `chat runtime keeps ide base path`() {
        val result = resolveRuntimeProjectRootValue(
            runtime = "chat",
            projectBasePath = "C:/repo/current-project"
        )

        assertEquals("C:/repo/current-project", result)
    }

    @Test
    fun `returns empty when ide base path is missing`() {
        val result = resolveRuntimeProjectRootValue(
            runtime = "opencode",
            projectBasePath = null
        )

        assertEquals("", result)
    }

    @Test
    fun `status line includes opencode context and tokens`() {
        val result = buildStatusLabelText(
            runtimeText = "Agent",
            activityText = "Готов",
            connectionText = "подключено",
            details = null,
            contextPercent = 37,
            tokenTotal = 1420
        )

        assertEquals("Agent | Готов | подключено | Контекст 37% | Токены 1420", result)
    }

    @Test
    fun `status line skips opencode metrics for non agent`() {
        val result = buildStatusLabelText(
            runtimeText = "Chat",
            activityText = "Готов",
            connectionText = "подключено",
            details = "ok",
            contextPercent = null,
            tokenTotal = null
        )

        assertEquals("Chat | Готов | подключено | ok", result)
    }

    @Test
    fun `context percent falls back to used and context window`() {
        val result = resolveContextPercent(
            percent = null,
            used = 1000,
            contextWindow = 200000
        )

        assertEquals(0, result)
    }

    @Test
    fun `cli token total uses input output and reasoning only`() {
        val result = opencodeCliTokenTotal(
            input = 120,
            output = 80,
            reasoning = 40
        )

        assertEquals(240, result)
    }

    @Test
    fun `status details prepend planning mode tag`() {
        val result = buildStatusDetails(
            connectionDetails = "ok",
            planModeEnabled = true
        )

        assertEquals("Планирование | ok", result)
    }

    @Test
    fun `extractLatestPendingQuestion returns newest unanswered clarification with choices`() {
        val question = extractLatestPendingQuestion(
            listOf(
                ChatMessageDto(
                    messageId = "m1",
                    role = "assistant",
                    content = "Which variant should I use?",
                    metadata = mapOf(
                        "question" to true,
                        "choices" to listOf("Variant A", "Variant B"),
                        "allowCustomAnswer" to true
                    ),
                    createdAt = Instant.parse("2026-03-15T10:00:00Z")
                )
            )
        )

        assertNotNull(question)
        assertEquals("Which variant should I use?", question?.title)
        assertEquals(listOf("Variant A", "Variant B"), question?.choices)
        assertTrue(question?.allowCustomAnswer == true)
    }

    @Test
    fun `extractLatestPendingQuestion returns null after user reply`() {
        val question = extractLatestPendingQuestion(
            listOf(
                ChatMessageDto(
                    messageId = "m1",
                    role = "assistant",
                    content = "Which variant should I use?",
                    metadata = mapOf("question" to true, "choices" to listOf("Variant A")),
                    createdAt = Instant.parse("2026-03-15T10:00:00Z")
                ),
                ChatMessageDto(
                    messageId = "m2",
                    role = "user",
                    content = "Variant A",
                    metadata = emptyMap(),
                    createdAt = Instant.parse("2026-03-15T10:01:00Z")
                )
            )
        )

        assertEquals(null, question)
    }
}

package ru.sber.aitestplugin.ui.toolwindow

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import ru.sber.aitestplugin.model.OpenCodeCommandDto

class OpenCodeAgentCommandControllerTest {

    @Test
    fun `mergeCommandCatalog keeps upstream command and injects aliases`() {
        val merged = OpenCodeAgentCommandController.mergeCommandCatalog(
            listOf(
                OpenCodeCommandDto(
                    name = "review",
                    description = "Upstream review",
                    source = "project"
                )
            )
        )

        val review = merged.first { it.name == "review" }
        assertEquals("project", review.source)
        assertFalse(review.alias)
        assertTrue(merged.any { it.name == "status" && it.alias })
        assertTrue(merged.any { it.name == "models" && it.alias })
    }

    @Test
    fun `filterCommandCatalog hides native hidden commands from suggestions`() {
        val merged = OpenCodeAgentCommandController.mergeCommandCatalog(emptyList())

        val filtered = OpenCodeAgentCommandController.filterCommandCatalog(merged, "")

        assertFalse(filtered.any { it.name == "new" })
        assertFalse(filtered.any { it.name == "sessions" })
        assertTrue(filtered.any { it.name == "help" })
    }

    @Test
    fun `parseSlashInput extracts command id raw input and arguments`() {
        val parsed = OpenCodeAgentCommandController.parseSlashInput("/review focus on tests")

        requireNotNull(parsed)
        assertEquals("review", parsed.commandId)
        assertEquals("focus on tests", parsed.rawInput)
        assertEquals(listOf("focus", "on", "tests"), parsed.arguments)
    }

    @Test
    fun `selectionText leaves no trailing space for native and inspect aliases`() {
        val statusText = OpenCodeAgentCommandController.selectionText(
            OpenCodeCommandDto(name = "status", alias = true)
        )
        val initText = OpenCodeAgentCommandController.selectionText(
            OpenCodeCommandDto(name = "init", alias = true)
        )

        assertEquals("/status", statusText)
        assertEquals("/init ", initText)
    }
}

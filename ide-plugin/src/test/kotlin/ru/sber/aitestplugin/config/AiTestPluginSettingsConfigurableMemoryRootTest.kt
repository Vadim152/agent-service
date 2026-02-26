package ru.sber.aitestplugin.config

import kotlin.test.Test
import kotlin.test.assertEquals

class AiTestPluginSettingsConfigurableMemoryRootTest {

    @Test
    fun `uses preferred root when present`() {
        val result = resolveMemoryProjectRootValue(
            preferredRoot = "C:/repo/from-field",
            scanProjectRoot = "C:/repo/from-settings",
            projectBasePath = "C:/repo/from-base"
        )

        assertEquals("C:/repo/from-field", result)
    }

    @Test
    fun `uses scan project root when preferred root is empty`() {
        val result = resolveMemoryProjectRootValue(
            preferredRoot = "  ",
            scanProjectRoot = "C:/repo/from-settings",
            projectBasePath = "C:/repo/from-base"
        )

        assertEquals("C:/repo/from-settings", result)
    }

    @Test
    fun `uses project base path as final fallback`() {
        val result = resolveMemoryProjectRootValue(
            preferredRoot = "",
            scanProjectRoot = null,
            projectBasePath = "C:/repo/from-base"
        )

        assertEquals("C:/repo/from-base", result)
    }

    @Test
    fun `returns empty when all candidates are blank`() {
        val result = resolveMemoryProjectRootValue(
            preferredRoot = " ",
            scanProjectRoot = " ",
            projectBasePath = null
        )

        assertEquals("", result)
    }
}

package ru.sber.aitestplugin.ui.dialogs

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import ru.sber.aitestplugin.config.AiTestPluginSettings

class FeatureDialogStateStorageTest {

    @Test
    fun `loads generate defaults from settings with fallback`() {
        val settings = AiTestPluginSettings(
            lastGenerateFeatureTargetPath = "stored/path.feature",
            lastGenerateFeatureCreateFile = false,
            lastGenerateFeatureOverwriteExisting = true
        )

        val storage = FeatureDialogStateStorage(settings)
        val options = storage.loadGenerateOptions("fallback/path.feature")

        assertEquals("stored/path.feature", options.targetPath)
        assertFalse(options.createFile)
        assertTrue(options.overwriteExisting)
    }

    @Test
    fun `loads apply defaults using fallback when absent`() {
        val settings = AiTestPluginSettings()
        val storage = FeatureDialogStateStorage(settings)

        val options = storage.loadApplyOptions("defaults/feature.feature")

        assertEquals("defaults/feature.feature", options.targetPath)
        assertTrue(options.createFile)
        assertFalse(options.overwriteExisting)
    }

    @Test
    fun `saves selected options back to settings`() {
        val settings = AiTestPluginSettings()
        val storage = FeatureDialogStateStorage(settings)

        storage.saveGenerateOptions(
            GenerateFeatureDialogOptions(
                targetPath = "new/generate.feature",
                createFile = false,
                overwriteExisting = true
            )
        )

        storage.saveApplyOptions(
            ApplyFeatureDialogOptions(
                targetPath = "apply/path.feature",
                createFile = false,
                overwriteExisting = true
            )
        )

        assertEquals("new/generate.feature", settings.lastGenerateFeatureTargetPath)
        assertFalse(settings.lastGenerateFeatureCreateFile)
        assertTrue(settings.lastGenerateFeatureOverwriteExisting)

        assertEquals("apply/path.feature", settings.lastApplyFeatureTargetPath)
        assertFalse(settings.lastApplyFeatureCreateFile)
        assertTrue(settings.lastApplyFeatureOverwriteExisting)
    }
}

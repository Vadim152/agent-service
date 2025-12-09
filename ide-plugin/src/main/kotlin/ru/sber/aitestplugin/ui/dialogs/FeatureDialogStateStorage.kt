package ru.sber.aitestplugin.ui.dialogs

import ru.sber.aitestplugin.config.AiTestPluginSettings

data class GenerateFeatureDialogOptions(
    val targetPath: String?,
    val createFile: Boolean,
    val overwriteExisting: Boolean,
    val language: String?
)

data class ApplyFeatureDialogOptions(
    val targetPath: String?,
    val createFile: Boolean,
    val overwriteExisting: Boolean
)

class FeatureDialogStateStorage(private val settings: AiTestPluginSettings) {

    fun loadGenerateOptions(fallbackTargetPath: String? = null): GenerateFeatureDialogOptions =
        GenerateFeatureDialogOptions(
            targetPath = settings.lastGenerateFeatureTargetPath ?: fallbackTargetPath,
            createFile = settings.lastGenerateFeatureCreateFile,
            overwriteExisting = settings.lastGenerateFeatureOverwriteExisting,
            language = settings.lastGenerateFeatureLanguage
        )

    fun saveGenerateOptions(options: GenerateFeatureDialogOptions) {
        settings.lastGenerateFeatureTargetPath = options.targetPath
        settings.lastGenerateFeatureCreateFile = options.createFile
        settings.lastGenerateFeatureOverwriteExisting = options.overwriteExisting
        settings.lastGenerateFeatureLanguage = options.language
    }

    fun loadApplyOptions(fallbackTargetPath: String? = null): ApplyFeatureDialogOptions =
        ApplyFeatureDialogOptions(
            targetPath = settings.lastApplyFeatureTargetPath ?: fallbackTargetPath,
            createFile = settings.lastApplyFeatureCreateFile,
            overwriteExisting = settings.lastApplyFeatureOverwriteExisting
        )

    fun saveApplyOptions(options: ApplyFeatureDialogOptions) {
        settings.lastApplyFeatureTargetPath = options.targetPath
        settings.lastApplyFeatureCreateFile = options.createFile
        settings.lastApplyFeatureOverwriteExisting = options.overwriteExisting
    }
}

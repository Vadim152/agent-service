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
            targetPath = settings.generateFeatureTargetPath ?: fallbackTargetPath,
            createFile = settings.generateFeatureCreateFile,
            overwriteExisting = settings.generateFeatureOverwriteExisting,
            language = settings.generateFeatureLanguage
        )

    fun saveGenerateOptions(options: GenerateFeatureDialogOptions) {
        settings.generateFeatureTargetPath = options.targetPath
        settings.generateFeatureCreateFile = options.createFile
        settings.generateFeatureOverwriteExisting = options.overwriteExisting
        settings.generateFeatureLanguage = options.language
    }

    fun loadApplyOptions(fallbackTargetPath: String? = null): ApplyFeatureDialogOptions =
        ApplyFeatureDialogOptions(
            targetPath = settings.applyFeatureTargetPath ?: fallbackTargetPath,
            createFile = settings.applyFeatureCreateFile,
            overwriteExisting = settings.applyFeatureOverwriteExisting
        )

    fun saveApplyOptions(options: ApplyFeatureDialogOptions) {
        settings.applyFeatureTargetPath = options.targetPath
        settings.applyFeatureCreateFile = options.createFile
        settings.applyFeatureOverwriteExisting = options.overwriteExisting
    }
}

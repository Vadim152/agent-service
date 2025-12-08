package ru.sber.aitestplugin.model

/** Запрос на запись/применение feature-файла. */
data class ApplyFeatureRequestDto(
    val projectRoot: String,
    val targetPath: String,
    val featureText: String,
    val createFile: Boolean = true,
    val overwriteExisting: Boolean = false
)

/** Ответ на применение feature-файла. */
data class ApplyFeatureResponseDto(
    val projectRoot: String,
    val targetPath: String,
    val status: String,
    val message: String? = null
)

package ru.sber.aitestplugin.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.project.Project
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.dialogs.ApplyFeatureDialog
import ru.sber.aitestplugin.ui.dialogs.FeatureDialogStateStorage
import java.nio.file.Paths
import javax.swing.JOptionPane

/**
 * Действие, отправляющее текущий feature-текст в backend для записи в файловую систему проекта.
 */
class ApplyFeatureAction : AnAction() {
    private val backendClient = HttpBackendClient()

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project
        val editor = e.getData(CommonDataKeys.EDITOR)
        if (project == null || editor == null) {
            JOptionPane.showMessageDialog(null, "Откройте feature-файл в редакторе")
            return
        }

        val document = editor.document
        val featureText = document.text
        if (featureText.isBlank()) {
            JOptionPane.showMessageDialog(null, "Текст feature-файла пуст")
            return
        }

        val projectRoot = project.basePath ?: ""
        val defaultTargetPath = e.getData(CommonDataKeys.VIRTUAL_FILE)?.path?.let { filePath ->
            val basePath = project.basePath?.let { Paths.get(it) }
            val absoluteFilePath = Paths.get(filePath)
            if (basePath != null) {
                try {
                    basePath.relativize(absoluteFilePath).toString()
                } catch (_: IllegalArgumentException) {
                    filePath
                }
            } else {
                filePath
            }
        }

        val stateStorage = FeatureDialogStateStorage(AiTestPluginSettingsService.getInstance().state)
        val dialogDefaults = stateStorage.loadApplyOptions(defaultTargetPath)
        val dialog = ApplyFeatureDialog(project, dialogDefaults)
        if (!dialog.showAndGet()) return

        val dialogOptions = dialog.selectedOptions()
        if (dialogOptions.targetPath.isNullOrBlank()) {
            JOptionPane.showMessageDialog(null, "Укажите путь к feature-файлу")
            return
        }

        stateStorage.saveApplyOptions(dialogOptions)

        val request = ApplyFeatureRequestDto(
            projectRoot = projectRoot,
            targetPath = dialogOptions.targetPath,
            featureText = featureText,
            createFile = dialogOptions.createFile,
            overwriteExisting = dialogOptions.overwriteExisting
        )

        var response: ApplyFeatureResponseDto? = null
        var error: Throwable? = null

        ProgressManager.getInstance().runProcessWithProgressSynchronously(
            {
                try {
                    response = backendClient.applyFeature(request)
                } catch (ex: Exception) {
                    error = ex
                }
            },
            "Applying feature",
            true,
            project
        )

        if (error != null) {
            val message = error?.message ?: "Unexpected error"
            notify(project, "Feature apply failed: $message", NotificationType.ERROR)
            return
        }

        val responseData = response ?: return
        val status = responseData.status.lowercase()
        val message = when (status) {
            "overwritten" -> "Feature overwritten at ${responseData.targetPath}"
            else -> "Feature created at ${responseData.targetPath}"
        }
        val fullMessage = listOfNotNull(message, responseData.message).joinToString(": ")
        notify(project, fullMessage, NotificationType.INFORMATION)
    }

    private fun notify(project: Project, message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }
}

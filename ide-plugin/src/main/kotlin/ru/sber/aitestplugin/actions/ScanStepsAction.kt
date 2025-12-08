package ru.sber.aitestplugin.actions

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.toolwindow.AiToolWindowPanel
import ru.sber.aitestplugin.model.ScanStepsResponseDto

/**
 * Действие для запуска полного сканирования шагов Cucumber в текущем проекте.
 */
class ScanStepsAction : AnAction() {
    private val backendClient = HttpBackendClient()

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val projectRoot = project.basePath
        if (projectRoot.isNullOrBlank()) {
            notify(project, "Project root is empty", NotificationType.WARNING)
            return
        }

        var response: ScanStepsResponseDto? = null
        var error: Throwable? = null

        ProgressManager.getInstance().runProcessWithProgressSynchronously(
            {
                try {
                    response = backendClient.scanSteps(projectRoot)
                } catch (ex: Exception) {
                    error = ex
                }
            },
            "Scanning Cucumber steps",
            true,
            project
        )

        if (error != null) {
            val message = error?.message ?: "Unexpected error"
            notify(project, "Scan failed: $message", NotificationType.ERROR)
            return
        }

        val responseData = response ?: return
        updateToolWindow(project, responseData)

        val summary = buildString {
            append("Found ${responseData.stepsCount} steps")
            val sampleCount = responseData.sampleSteps?.size ?: 0
            if (sampleCount > 0) {
                append(", sample: $sampleCount")
            }
            append(". Updated at ${responseData.updatedAt}.")
        }

        notify(project, summary, NotificationType.INFORMATION)
    }

    private fun notify(project: Project, message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }

    private fun updateToolWindow(project: Project, response: ScanStepsResponseDto) {
        val toolWindow = ToolWindowManager.getInstance(project).getToolWindow("AI Cucumber Assistant")
        val panel = toolWindow?.contentManager?.contents
            ?.mapNotNull { it.component as? AiToolWindowPanel }
            ?.firstOrNull()
        panel?.showScanResult(response)
    }
}

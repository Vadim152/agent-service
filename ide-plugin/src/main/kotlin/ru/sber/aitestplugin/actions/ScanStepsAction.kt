package ru.sber.aitestplugin.actions

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.toolwindow.AiToolWindowPanel
import ru.sber.aitestplugin.ui.toolwindow.ToolWindowIds
import ru.sber.aitestplugin.model.ScanStepsResponseDto

/**
 * Действие для запуска полного сканирования шагов Cucumber в текущем проекте.
 */
class ScanStepsAction : AnAction() {
    private val backendClient = HttpBackendClient()
    private val settings = AiTestPluginSettingsService.getInstance().settings

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath
        if (projectRoot.isNullOrBlank()) {
            notify(project, "Project root is empty", NotificationType.WARNING)
            return
        }

        settings.scanProjectRoot = projectRoot

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Scanning Cucumber steps", true) {
            private var response: ScanStepsResponseDto? = null

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Calling backend..."
                response = backendClient.scanSteps(projectRoot)
            }

            override fun onSuccess() {
                val responseData = response ?: return
                updateToolWindow(project, responseData)

                val summary = buildString {
                    append("Found ${responseData.stepsCount} steps")
                    val sampleCount = responseData.sampleSteps?.size ?: 0
                    if (sampleCount > 0) {
                        append(", sample: $sampleCount")
                    }
                    if (responseData.unmappedSteps.isNotEmpty()) {
                        append(", unmapped: ${responseData.unmappedSteps.size}")
                    }
                    append(". Updated at ${responseData.updatedAt}.")
                }

                notify(project, summary, NotificationType.INFORMATION)
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Unexpected error"
                notify(project, "Scan failed: $message", NotificationType.ERROR)
            }
        })
    }

    private fun notify(project: Project, message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("Агентум")
            .createNotification(message, type)
            .notify(project)
    }

    private fun updateToolWindow(project: Project, response: ScanStepsResponseDto) {
        val toolWindow = ToolWindowIds.findToolWindow(project)
        val panel = toolWindow?.contentManager?.contents
            ?.mapNotNull { it.component as? AiToolWindowPanel }
            ?.firstOrNull()
        panel?.showScanResult(response)
    }
}

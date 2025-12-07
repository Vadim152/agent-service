package ru.sber.aitestplugin.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.progress.ProgressManager
import ru.sber.aitestplugin.services.HttpBackendClient
import javax.swing.JOptionPane

/**
 * Действие для запуска полного сканирования шагов Cucumber в текущем проекте.
 */
class ScanStepsAction : AnAction() {
    private val backendClient = HttpBackendClient()

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val projectRoot = project.basePath ?: return

        ProgressManager.getInstance().runProcessWithProgressSynchronously(
            {
                try {
                    val response = backendClient.scanSteps(projectRoot)
                    // TODO: обновить UI Tool Window/уведомление результатом
                } catch (ex: Exception) {
                    JOptionPane.showMessageDialog(null, "Scan failed: ${ex.message}")
                }
            },
            "Scanning Cucumber steps",
            true,
            project
        )
    }
}

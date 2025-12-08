package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.ui.JBSplitter
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel

/**
 * Основная панель Tool Window с кнопкой сканирования и таблицей шагов.
 */
class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient()
) : JPanel(BorderLayout()) {
    private val scanButton = JButton("Scan steps")
    private val projectRootField = JBTextField(project.basePath ?: "")
    private val stepsList = JBList<StepDefinitionDto>()
    private val statusLabel = JLabel("Index not yet built")

    init {
        border = JBUI.Borders.empty(8)
        layout = BorderLayout()
        val topPanel = JPanel(GridBagLayout())
        val gbc = GridBagConstraints().apply {
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
        }
        topPanel.add(JLabel("Project root:"), gbc)
        topPanel.add(projectRootField, gbc)
        topPanel.add(scanButton, gbc)

        val listWrapper = JBScrollPane(stepsList)
        val splitter = JBSplitter(true, 0.8f).apply {
            firstComponent = listWrapper
            secondComponent = statusLabel
        }

        add(topPanel, BorderLayout.NORTH)
        add(splitter, BorderLayout.CENTER)

        scanButton.addActionListener {
            runScanSteps()
        }
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        stepsList.setListData(response.sampleSteps.orEmpty().toTypedArray())
        statusLabel.text = "Found ${response.stepsCount} steps. Updated at ${response.updatedAt}"
    }

    private fun runScanSteps() {
        val projectRoot = projectRootField.text.trim()
        if (projectRoot.isBlank()) {
            statusLabel.text = "Project root is empty"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        statusLabel.text = "Scanning..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Scanning Cucumber steps", true) {
            private var responseSteps = emptyList<StepDefinitionDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Calling backend..."
                val response = backendClient.scanSteps(projectRoot)
                responseSteps = response.sampleSteps.orEmpty()
                statusMessage = "Found ${response.stepsCount} steps. Updated at ${response.updatedAt}"
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                statusLabel.text = statusMessage
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Unexpected error"
                statusLabel.text = "Scan failed: $message"
                notify(message, NotificationType.ERROR)
            }
        })
    }

    private fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }
}

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
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Component
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.DefaultListCellRenderer

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
    private val unmappedList = JBList<UnmappedStepDto>()
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

        stepsList.emptyText.text = "No sample steps yet"
        unmappedList.emptyText.text = "No unmapped steps"
        unmappedList.cellRenderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(
                list: javax.swing.JList<*>,
                value: Any?,
                index: Int,
                isSelected: Boolean,
                cellHasFocus: Boolean
            ): Component {
                val unmapped = value as? UnmappedStepDto
                val reason = unmapped?.reason?.let { " — $it" } ?: ""
                return super.getListCellRendererComponent(list, "${unmapped?.text ?: ""}$reason", index, isSelected, cellHasFocus)
            }
        }

        val stepsPanel = JPanel(BorderLayout()).apply {
            add(JLabel("Sample steps"), BorderLayout.NORTH)
            add(JBScrollPane(stepsList), BorderLayout.CENTER)
        }

        val unmappedPanel = JPanel(BorderLayout()).apply {
            add(JLabel("Unmapped steps"), BorderLayout.NORTH)
            add(JBScrollPane(unmappedList), BorderLayout.CENTER)
        }

        val listsSplitter = JBSplitter(false, 0.5f).apply {
            firstComponent = stepsPanel
            secondComponent = unmappedPanel
        }

        add(topPanel, BorderLayout.NORTH)
        add(listsSplitter, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)

        scanButton.addActionListener {
            runScanSteps()
        }
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        stepsList.setListData(response.sampleSteps.orEmpty().toTypedArray())
        unmappedList.setListData(response.unmappedSteps.toTypedArray())
        val unmappedMessage = if (response.unmappedSteps.isEmpty()) "" else ", unmapped: ${response.unmappedSteps.size}"
        statusLabel.text = "Found ${response.stepsCount} steps$unmappedMessage. Updated at ${response.updatedAt}"
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        unmappedList.setListData(unmappedSteps.toTypedArray())
        statusLabel.text = if (unmappedSteps.isEmpty()) "No unmapped steps" else "Unmapped steps: ${unmappedSteps.size}"
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
            private var responseUnmapped = emptyList<UnmappedStepDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Calling backend..."
                val response = backendClient.scanSteps(projectRoot)
                responseSteps = response.sampleSteps.orEmpty()
                responseUnmapped = response.unmappedSteps
                val unmappedMessage = if (responseUnmapped.isEmpty()) "" else ", unmapped: ${responseUnmapped.size}"
                statusMessage = "Found ${response.stepsCount} steps$unmappedMessage. Updated at ${response.updatedAt}"
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                unmappedList.setListData(responseUnmapped.toTypedArray())
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

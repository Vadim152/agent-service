package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.ui.JBSplitter
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBEditorPane
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.model.GenerateFeatureOptionsDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.dialogs.FeatureDialogStateStorage
import ru.sber.aitestplugin.ui.dialogs.GenerateFeatureDialogOptions
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
    private val stateStorage = FeatureDialogStateStorage(AiTestPluginSettingsService.getInstance().settings)
    private val scanButton = JButton("Scan steps")
    private val projectRootField = JBTextField(project.basePath ?: "")
    private val testCaseArea = JBTextArea(6, 60)
    private val generateButton = JButton("Generate")
    private val targetPathField = JBTextField()
    private val createFileCheckbox = JBCheckBox("Create file if missing")
    private val overwriteCheckbox = JBCheckBox("Overwrite existing file")
    private val languageField = JBTextField()
    private val featureTextPane = JBEditorPane().apply { isEditable = false }
    private val stepsList = JBList<StepDefinitionDto>()
    private val stepsLabel = JLabel("Sample steps")
    private val unmappedList = JBList<UnmappedStepDto>()
    private val statusLabel = JLabel("Index not yet built")

    init {
        border = JBUI.Borders.empty(8)
        layout = BorderLayout()
        val options = stateStorage.loadGenerateOptions(project.basePath)
        targetPathField.text = options.targetPath ?: ""
        createFileCheckbox.isSelected = options.createFile
        overwriteCheckbox.isSelected = options.overwriteExisting

        val topPanel = JPanel(GridBagLayout())
        val gbc = GridBagConstraints().apply {
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
        }
        topPanel.add(JLabel("Project root:"), gbc)
        topPanel.add(projectRootField, gbc)
        topPanel.add(scanButton, gbc)

        testCaseArea.lineWrap = true
        testCaseArea.wrapStyleWord = true

        stepsList.emptyText.text = "No used steps yet"
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

        val generationPanel = JPanel(BorderLayout()).apply {
            border = JBUI.Borders.emptyTop(8)
            add(JLabel("Test case:"), BorderLayout.NORTH)
            add(JBScrollPane(testCaseArea), BorderLayout.CENTER)
            add(buildOptionsPanel(), BorderLayout.SOUTH)
        }

        val featurePanel = JPanel(BorderLayout()).apply {
            add(JLabel("Generated feature"), BorderLayout.NORTH)
            add(JBScrollPane(featureTextPane), BorderLayout.CENTER)
        }

        val stepsPanel = JPanel(BorderLayout()).apply {
            add(stepsLabel, BorderLayout.NORTH)
            add(JBScrollPane(stepsList), BorderLayout.CENTER)
        }

        val unmappedPanel = JPanel(BorderLayout()).apply {
            add(JLabel("Unmapped steps"), BorderLayout.NORTH)
            add(JBScrollPane(unmappedList), BorderLayout.CENTER)
        }

        val stepsSplitter = JBSplitter(true, 0.5f).apply {
            firstComponent = stepsPanel
            secondComponent = unmappedPanel
        }

        val outputSplitter = JBSplitter(false, 0.55f).apply {
            firstComponent = featurePanel
            secondComponent = stepsSplitter
        }

        val contentSplitter = JBSplitter(true, 0.4f).apply {
            firstComponent = generationPanel
            secondComponent = outputSplitter
        }

        add(topPanel, BorderLayout.NORTH)
        add(contentSplitter, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)

        scanButton.addActionListener {
            runScanSteps()
        }

        generateButton.addActionListener {
            runGenerateFeature()
        }
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        stepsList.setListData(response.sampleSteps.orEmpty().toTypedArray())
        unmappedList.setListData(emptyArray())
        stepsLabel.text = "Sample steps"
        statusLabel.text = "Found ${response.stepsCount} steps. Updated at ${response.updatedAt}"
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

    private fun runGenerateFeature() {
        val projectRoot = projectRootField.text.trim().ifBlank { project.basePath ?: "" }
        if (projectRoot.isBlank()) {
            statusLabel.text = "Project root is empty"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        val testCaseText = testCaseArea.text.trim()
        if (testCaseText.isBlank()) {
            statusLabel.text = "Test case is empty"
            notify("Введите текст тесткейса", NotificationType.WARNING)
            return
        }

        val dialogOptions = GenerateFeatureDialogOptions(
            targetPath = targetPathField.text.trim().takeIf { it.isNotEmpty() },
            createFile = createFileCheckbox.isSelected,
            overwriteExisting = overwriteCheckbox.isSelected
        )
        stateStorage.saveGenerateOptions(dialogOptions)

        val request = GenerateFeatureRequestDto(
            projectRoot = projectRoot,
            testCaseText = testCaseText,
            targetPath = dialogOptions.targetPath,
            options = GenerateFeatureOptionsDto(
                createFile = dialogOptions.createFile,
                overwriteExisting = dialogOptions.overwriteExisting,
                language = languageField.text.trim().takeIf { it.isNotEmpty() }
            )
        )

        statusLabel.text = "Generating feature..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Generating feature", true) {
            private var response: GenerateFeatureResponseDto? = null

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Sending test case to backend..."
                response = backendClient.generateFeature(request)
            }

            override fun onSuccess() {
                val responseData = response ?: return
                showGenerateResult(responseData)
                val unmappedCount = responseData.unmappedSteps.size
                val usedCount = responseData.usedSteps.size
                statusLabel.text = "Feature generated. Used steps: $usedCount. Unmapped: $unmappedCount"
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Unexpected error"
                statusLabel.text = "Generation failed: $message"
                notify(message, NotificationType.ERROR)
            }
        })
    }

    private fun showGenerateResult(response: GenerateFeatureResponseDto) {
        featureTextPane.text = response.featureText
        stepsList.setListData(response.usedSteps.toTypedArray())
        stepsLabel.text = "Used steps"
        unmappedList.setListData(response.unmappedSteps.toTypedArray())
    }

    private fun buildOptionsPanel(): JPanel {
        val optionsPanel = JPanel(GridBagLayout())
        optionsPanel.border = JBUI.Borders.emptyTop(8)
        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            anchor = GridBagConstraints.WEST
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
            ipadx = 4
            ipady = 4
        }

        optionsPanel.add(JLabel("Target path (relative to project root):"), gbc)
        gbc.gridy++
        optionsPanel.add(targetPathField, gbc)

        gbc.gridy++
        optionsPanel.add(createFileCheckbox, gbc)

        gbc.gridy++
        optionsPanel.add(overwriteCheckbox, gbc)

        gbc.gridy++
        optionsPanel.add(JLabel("Language (optional):"), gbc)
        gbc.gridy++
        optionsPanel.add(languageField, gbc)

        gbc.gridy++
        optionsPanel.add(generateButton, gbc)

        return optionsPanel
    }

    private fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }
}

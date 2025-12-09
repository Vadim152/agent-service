package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.ui.JBSplitter
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.model.GenerateFeatureOptionsDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.dialogs.FeatureDialogStateStorage
import ru.sber.aitestplugin.ui.dialogs.GenerateFeatureDialogOptions
import java.awt.BorderLayout
import java.awt.Component
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.DefaultListCellRenderer
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
    private val stateStorage = FeatureDialogStateStorage(AiTestPluginSettingsService.getInstance().settings)
    private val generateDefaults: GenerateFeatureDialogOptions = stateStorage.loadGenerateOptions(project.basePath)
    private val scanButton = JButton("Scan steps")
    private val projectRootField = JBTextField(project.basePath ?: "")
    private val stepsList = JBList<StepDefinitionDto>()
    private val unmappedList = JBList<UnmappedStepDto>()
    private val testCaseInput = JBTextArea(5, 20)
    private val targetPathField = JBTextField(generateDefaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox("Create file if missing", generateDefaults.createFile)
    private val overwriteCheckbox = JBCheckBox("Overwrite existing file", generateDefaults.overwriteExisting)
    private val languageField = JBTextField(generateDefaults.language ?: "")
    private val generateButton = JButton("Generate")
    private val featureTextPane = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
    }
    private val usedStepsList = JBList<StepDefinitionDto>()
    private val generatedUnmappedList = JBList<UnmappedStepDto>()
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
        usedStepsList.emptyText.text = "Used steps will appear here"
        generatedUnmappedList.emptyText.text = "Generated unmapped steps will appear here"
        testCaseInput.lineWrap = true
        testCaseInput.wrapStyleWord = true
        configureUnmappedRenderer(unmappedList)
        configureUnmappedRenderer(generatedUnmappedList)
        usedStepsList.cellRenderer = object : DefaultListCellRenderer() {
            override fun getListCellRendererComponent(
                list: javax.swing.JList<*>,
                value: Any?,
                index: Int,
                isSelected: Boolean,
                cellHasFocus: Boolean
            ): Component {
                val step = value as? StepDefinitionDto
                val text = step?.let { "${it.keyword} ${it.pattern}" } ?: ""
                return super.getListCellRendererComponent(list, text, index, isSelected, cellHasFocus)
            }
        }
        featureTextPane.border = JBUI.Borders.empty()

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

        val generationForm = JPanel(GridBagLayout()).apply {
            border = JBUI.Borders.empty(4)
            val formConstraints = GridBagConstraints().apply {
                gridx = 0
                gridy = 0
                anchor = GridBagConstraints.WEST
                fill = GridBagConstraints.HORIZONTAL
                weightx = 1.0
                ipadx = 4
                ipady = 4
            }

            add(JLabel("Test case:"), formConstraints)
            formConstraints.gridy++
            formConstraints.fill = GridBagConstraints.BOTH
            formConstraints.weighty = 1.0
            add(JBScrollPane(testCaseInput), formConstraints)

            formConstraints.gridy++
            formConstraints.fill = GridBagConstraints.HORIZONTAL
            formConstraints.weighty = 0.0
            add(JLabel("Target path (relative to project root):"), formConstraints)
            formConstraints.gridy++
            add(targetPathField, formConstraints)

            formConstraints.gridy++
            add(createFileCheckbox, formConstraints)

            formConstraints.gridy++
            add(overwriteCheckbox, formConstraints)

            formConstraints.gridy++
            add(JLabel("Language (optional):"), formConstraints)
            formConstraints.gridy++
            add(languageField, formConstraints)

            formConstraints.gridy++
            add(generateButton, formConstraints)
        }

        val featurePanel = JPanel(BorderLayout()).apply {
            add(JLabel("Generated feature"), BorderLayout.NORTH)
            add(JBScrollPane(featureTextPane), BorderLayout.CENTER)
        }

        val usedStepsPanel = JPanel(BorderLayout()).apply {
            add(JLabel("Used steps"), BorderLayout.NORTH)
            add(JBScrollPane(usedStepsList), BorderLayout.CENTER)
        }

        val generatedUnmappedPanel = JPanel(BorderLayout()).apply {
            add(JLabel("Generated unmapped steps"), BorderLayout.NORTH)
            add(JBScrollPane(generatedUnmappedList), BorderLayout.CENTER)
        }

        val generationStepsSplitter = JBSplitter(true, 0.5f).apply {
            firstComponent = usedStepsPanel
            secondComponent = generatedUnmappedPanel
        }

        val generationResultSplitter = JBSplitter(false, 0.5f).apply {
            firstComponent = featurePanel
            secondComponent = generationStepsSplitter
        }

        val generationPanel = JPanel(BorderLayout()).apply {
            add(generationForm, BorderLayout.NORTH)
            add(generationResultSplitter, BorderLayout.CENTER)
        }

        val mainSplitter = JBSplitter(true, 0.4f).apply {
            firstComponent = listsSplitter
            secondComponent = generationPanel
        }

        add(topPanel, BorderLayout.NORTH)
        add(mainSplitter, BorderLayout.CENTER)
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
        unmappedList.setListData(response.unmappedSteps.toTypedArray())
        val unmappedMessage = if (response.unmappedSteps.isEmpty()) "" else ", unmapped: ${response.unmappedSteps.size}"
        statusLabel.text = "Found ${response.stepsCount} steps$unmappedMessage. Updated at ${response.updatedAt}"
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        generatedUnmappedList.setListData(unmappedSteps.toTypedArray())
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

    private fun runGenerateFeature() {
        val projectRoot = projectRootField.text.trim().ifEmpty { project.basePath.orEmpty() }
        if (projectRoot.isBlank()) {
            statusLabel.text = "Project root is empty"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        val testCaseText = testCaseInput.text.trim()
        if (testCaseText.isBlank()) {
            statusLabel.text = "Test case is empty"
            notify("Введите текст тесткейса", NotificationType.WARNING)
            return
        }

        val dialogOptions = GenerateFeatureDialogOptions(
            targetPath = targetPathField.text.trim().takeIf { it.isNotEmpty() },
            createFile = createFileCheckbox.isSelected,
            overwriteExisting = overwriteCheckbox.isSelected,
            language = languageField.text.trim().takeIf { it.isNotEmpty() }
        )
        stateStorage.saveGenerateOptions(dialogOptions)

        val request = GenerateFeatureRequestDto(
            projectRoot = projectRoot,
            testCaseText = testCaseText,
            targetPath = dialogOptions.targetPath,
            options = GenerateFeatureOptionsDto(
                createFile = dialogOptions.createFile,
                overwriteExisting = dialogOptions.overwriteExisting,
                language = dialogOptions.language
            )
        )

        statusLabel.text = "Generating feature..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Generating feature", true) {
            private var featureText: String = ""
            private var usedSteps: List<StepDefinitionDto> = emptyList()
            private var unmapped: List<UnmappedStepDto> = emptyList()

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Sending test case to backend..."
                val response = backendClient.generateFeature(request)
                featureText = response.featureText
                usedSteps = response.usedSteps
                unmapped = response.unmappedSteps
            }

            override fun onSuccess() {
                featureTextPane.text = featureText
                featureTextPane.caretPosition = 0
                usedStepsList.setListData(usedSteps.toTypedArray())
                generatedUnmappedList.setListData(unmapped.toTypedArray())
                val unmappedMessage = if (unmapped.isEmpty()) "" else ", unmapped: ${unmapped.size}"
                statusLabel.text = "Feature generated. Used: ${usedSteps.size}$unmappedMessage"
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Unexpected error"
                statusLabel.text = "Generate failed: $message"
                notify(message, NotificationType.ERROR)
            }
        })
    }

    private fun configureUnmappedRenderer(list: JBList<UnmappedStepDto>) {
        list.cellRenderer = object : DefaultListCellRenderer() {
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
    }

    private fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }
}

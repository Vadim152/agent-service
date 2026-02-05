package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.icons.AllIcons
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.config.toZephyrAuthDto
import ru.sber.aitestplugin.config.zephyrAuthValidationError
import ru.sber.aitestplugin.model.GenerateFeatureOptionsDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.JobCreateRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.dialogs.FeatureDialogStateStorage
import ru.sber.aitestplugin.ui.dialogs.GenerateFeatureDialogOptions
import java.awt.BorderLayout
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.SwingConstants

/**
 * Основная панель Tool Window с генерацией сценария.
 */
class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient()
) : JPanel(BorderLayout()) {
    private val settings = AiTestPluginSettingsService.getInstance().settings
    private val stateStorage = FeatureDialogStateStorage(settings)
    private val generateDefaults: GenerateFeatureDialogOptions = stateStorage.loadGenerateOptions(project.basePath)
    private val testCaseInput = JBTextArea(5, 20)
    private val targetPathField = JBTextField(generateDefaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox("Создать файл, если отсутствует", generateDefaults.createFile)
    private val overwriteCheckbox = JBCheckBox("Перезаписать существующий файл", generateDefaults.overwriteExisting)
    private val generateButton = JButton("Сгенерировать", AllIcons.Actions.Execute).apply {
        foreground = JBColor(0x0B874B, 0x7DE390)
        background = JBColor(0xE7F6EC, 0x284133)
        border = JBUI.Borders.empty(6, 12)
        isOpaque = true
    }
    private val statusLabel = JLabel("Индекс ещё не построен", AllIcons.General.Information, SwingConstants.LEADING)

    init {
        border = JBUI.Borders.empty(12)
        layout = BorderLayout()

        testCaseInput.lineWrap = true
        testCaseInput.wrapStyleWord = true

        val generationForm = createCardPanel().apply {
            add(createSectionLabel("Генерация сценария"), BorderLayout.NORTH)
            add(buildGenerationForm(), BorderLayout.CENTER)
        }

        add(generationForm, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)

        generateButton.addActionListener {
            runGenerateFeature()
        }
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        val unmappedMessage = if (response.unmappedSteps.isEmpty()) "" else ", неотображённых: ${response.unmappedSteps.size}"
        statusLabel.icon = AllIcons.General.InspectionsOK
        statusLabel.text = "Найдено ${response.stepsCount} шагов$unmappedMessage • Обновлено ${response.updatedAt}"
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        statusLabel.icon = if (unmappedSteps.isEmpty()) AllIcons.General.InspectionsOK else AllIcons.General.Warning
        statusLabel.text = if (unmappedSteps.isEmpty()) {
            "Неотображённых шагов нет"
        } else {
            "Неотображённые шаги: ${unmappedSteps.size}"
        }
    }

    private fun runGenerateFeature() {
        val projectRoot = settings.scanProjectRoot.orEmpty().ifEmpty { project.basePath.orEmpty() }
        if (projectRoot.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Путь к проекту не указан"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        settings.scanProjectRoot = projectRoot

        val testCaseText = testCaseInput.text.trim()
        if (testCaseText.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Текст тесткейса пустой"
            notify("Введите текст тесткейса", NotificationType.WARNING)
            return
        }

        val authError = settings.zephyrAuthValidationError()
        if (authError != null) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Не заполнены данные авторизации Jira/Zephyr"
            notify(authError, NotificationType.WARNING)
            return
        }

        val dialogOptions = GenerateFeatureDialogOptions(
            targetPath = targetPathField.text.trim().takeIf { it.isNotEmpty() },
            createFile = createFileCheckbox.isSelected,
            overwriteExisting = overwriteCheckbox.isSelected,
            language = generateDefaults.language
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
            ),
            zephyrAuth = settings.toZephyrAuthDto()
        )

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "Генерация feature..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Генерация feature", true) {
            private var usedSteps: List<StepDefinitionDto> = emptyList()
            private var unmapped: List<UnmappedStepDto> = emptyList()
            private var finalStatus: String = "queued"
            private var incidentUri: String? = null

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Создание Job..."
                val job = backendClient.createJob(
                    JobCreateRequestDto(
                        projectRoot = request.projectRoot,
                        testCaseText = request.testCaseText,
                        targetPath = request.targetPath,
                        profile = "quick",
                        createFile = request.options?.createFile ?: false,
                        overwriteExisting = request.options?.overwriteExisting ?: false,
                        language = request.options?.language
                    )
                )

                var attemptsLeft = 120
                while (attemptsLeft-- > 0) {
                    val status = backendClient.getJob(job.jobId)
                    finalStatus = status.status
                    incidentUri = status.incidentUri
                    indicator.text = when (status.status) {
                        "running" -> "Запуск"
                        "needs_attention" -> "Эскалация"
                        "succeeded" -> "Повторный запуск/успех"
                        else -> "Диагностика"
                    }
                    if (status.status in setOf("succeeded", "needs_attention", "failed", "cancelled")) {
                        break
                    }
                    Thread.sleep(500)
                }

                indicator.text = "Получение финального feature..."
                val response = backendClient.generateFeature(request)
                usedSteps = response.usedSteps
                unmapped = response.unmappedSteps
            }

            override fun onSuccess() {
                val unmappedMessage = if (unmapped.isEmpty()) "" else ", неотображённых: ${unmapped.size}"
                statusLabel.icon = if (finalStatus == "succeeded") AllIcons.General.InspectionsOK else AllIcons.General.Warning
                statusLabel.text = "Статус: $finalStatus. Использовано: ${usedSteps.size}$unmappedMessage"
                if (!incidentUri.isNullOrBlank()) {
                    notify("Открыть инцидент: $incidentUri", NotificationType.INFORMATION)
                }
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Непредвиденная ошибка"
                statusLabel.icon = AllIcons.General.Error
                statusLabel.text = "Генерация не удалась: $message"
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

    private fun buildGenerationForm(): JPanel {
        val panel = JPanel(GridBagLayout())
        panel.background = JBColor.PanelBackground
        val formConstraints = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            anchor = GridBagConstraints.WEST
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
            ipadx = 4
            ipady = 4
            insets = JBUI.insetsBottom(8)
        }

        panel.add(JLabel("Текст тесткейса"), formConstraints)
        formConstraints.gridy++
        formConstraints.fill = GridBagConstraints.BOTH
        formConstraints.weighty = 1.0
        panel.add(JBScrollPane(testCaseInput), formConstraints)

        formConstraints.gridy++
        formConstraints.fill = GridBagConstraints.HORIZONTAL
        formConstraints.weighty = 0.0
        panel.add(JLabel("Целевой путь (относительно корня проекта)"), formConstraints)
        formConstraints.gridy++
        panel.add(targetPathField, formConstraints)

        formConstraints.gridy++
        panel.add(createHintLabel("Например: src/test/resources/features"), formConstraints)

        formConstraints.gridy++
        panel.add(createFileCheckbox, formConstraints)

        formConstraints.gridy++
        panel.add(overwriteCheckbox, formConstraints)

        formConstraints.gridy++
        formConstraints.insets = JBUI.insets(12, 0, 0, 0)
        panel.add(generateButton, formConstraints)
        return panel
    }

    private fun createSectionLabel(text: String): JLabel = JLabel(text).apply {
        border = JBUI.Borders.emptyBottom(6)
    }

    private fun createHintLabel(text: String): JLabel = JLabel(text).apply {
        foreground = JBColor.GRAY
    }

    private fun createCardPanel(): JPanel = JPanel(BorderLayout()).apply {
        background = JBColor.PanelBackground
        border = JBUI.Borders.compound(
            JBUI.Borders.customLine(JBColor.border(), 1),
            JBUI.Borders.empty(12)
        )
    }
}

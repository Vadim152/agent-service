package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.icons.AllIcons
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.JBSplitter
import com.intellij.ui.JBColor
import com.intellij.ui.SimpleTextAttributes
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
import java.awt.Font
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
    private val stateStorage = FeatureDialogStateStorage(AiTestPluginSettingsService.getInstance().settings)
    private val generateDefaults: GenerateFeatureDialogOptions = stateStorage.loadGenerateOptions(project.basePath)
    private val scanButton = JButton("Сканировать шаги", AllIcons.Actions.Search).apply {
        foreground = JBColor(0x0B5CAD, 0x78A6FF)
        background = JBColor(0xE8F1FF, 0x2C3F57)
        border = JBUI.Borders.empty(6, 12)
        isOpaque = true
    }
    private val projectRootField = JBTextField(project.basePath ?: "")
    private val stepsList = JBList<StepDefinitionDto>()
    private val unmappedList = JBList<UnmappedStepDto>()
    private val testCaseInput = JBTextArea(5, 20)
    private val targetPathField = JBTextField(generateDefaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox("Создать файл, если отсутствует", generateDefaults.createFile)
    private val overwriteCheckbox = JBCheckBox("Перезаписать существующий файл", generateDefaults.overwriteExisting)
    private val languageField = JBTextField(generateDefaults.language ?: "")
    private val generateButton = JButton("Сгенерировать", AllIcons.Actions.Execute).apply {
        foreground = JBColor(0x0B874B, 0x7DE390)
        background = JBColor(0xE7F6EC, 0x284133)
        border = JBUI.Borders.empty(6, 12)
        isOpaque = true
    }
    private val featureTextPane = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
    }
    private val usedStepsList = JBList<StepDefinitionDto>()
    private val generatedUnmappedList = JBList<UnmappedStepDto>()
    private val statusLabel = JLabel("Индекс ещё не построен", AllIcons.General.Information)

    init {
        border = JBUI.Borders.empty(12)
        layout = BorderLayout()
        val topPanel = createCardPanel().apply {
            val section = createSectionLabel("Сканирование проекта")
            add(section, BorderLayout.NORTH)
            add(buildScanControls(), BorderLayout.CENTER)
        }

        stepsList.emptyText.text = "Шаги ещё не найдены"
        unmappedList.emptyText.text = "Неотображённые шаги отсутствуют"
        usedStepsList.emptyText.text = "Использованные шаги появятся здесь"
        generatedUnmappedList.emptyText.text = "Новые неотображённые шаги появятся здесь"
        testCaseInput.lineWrap = true
        testCaseInput.wrapStyleWord = true
        configureStepRenderer(stepsList)
        configureStepRenderer(usedStepsList)
        configureUnmappedRenderer(unmappedList)
        configureUnmappedRenderer(generatedUnmappedList)
        featureTextPane.border = JBUI.Borders.empty()

        val stepsPanel = createCardPanel().apply {
            add(createSectionLabel("Найденные шаги"), BorderLayout.NORTH)
            add(JBScrollPane(stepsList), BorderLayout.CENTER)
        }

        val unmappedPanel = createCardPanel().apply {
            add(createSectionLabel("Неотображённые шаги"), BorderLayout.NORTH)
            add(JBScrollPane(unmappedList), BorderLayout.CENTER)
        }

        val listsSplitter = JBSplitter(false, 0.5f).apply {
            firstComponent = stepsPanel
            secondComponent = unmappedPanel
        }

        val generationForm = createCardPanel().apply {
            add(createSectionLabel("Генерация сценария"), BorderLayout.NORTH)
            add(buildGenerationForm(), BorderLayout.CENTER)
        }

        val featurePanel = createCardPanel().apply {
            add(createSectionLabel("Сгенерированный feature"), BorderLayout.NORTH)
            add(JBScrollPane(featureTextPane), BorderLayout.CENTER)
        }

        val usedStepsPanel = createCardPanel().apply {
            add(createSectionLabel("Использованные шаги"), BorderLayout.NORTH)
            add(JBScrollPane(usedStepsList), BorderLayout.CENTER)
        }

        val generatedUnmappedPanel = createCardPanel().apply {
            add(createSectionLabel("Новые неотображённые шаги"), BorderLayout.NORTH)
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
        val unmappedMessage = if (response.unmappedSteps.isEmpty()) "" else ", неотображённых: ${response.unmappedSteps.size}"
        statusLabel.icon = AllIcons.General.InspectionsOK
        statusLabel.text = "Найдено ${response.stepsCount} шагов$unmappedMessage • Обновлено ${response.updatedAt}"
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        generatedUnmappedList.setListData(unmappedSteps.toTypedArray())
        statusLabel.icon = if (unmappedSteps.isEmpty()) AllIcons.General.InspectionsOK else AllIcons.General.Warning
        statusLabel.text = if (unmappedSteps.isEmpty()) "Неотображённых шагов нет" else "Неотображённые шаги: ${unmappedSteps.size}"
    }

    private fun runScanSteps() {
        val projectRoot = projectRootField.text.trim()
        if (projectRoot.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Путь к проекту не указан"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "Идёт сканирование проекта..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Сканирование шагов Cucumber", true) {
            private var responseSteps = emptyList<StepDefinitionDto>()
            private var responseUnmapped = emptyList<UnmappedStepDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Обращение к сервису..."
                val response = backendClient.scanSteps(projectRoot)
                responseSteps = response.sampleSteps.orEmpty()
                responseUnmapped = response.unmappedSteps
                val unmappedMessage = if (responseUnmapped.isEmpty()) "" else ", неотображённых: ${responseUnmapped.size}"
                statusMessage = "Найдено ${response.stepsCount} шагов$unmappedMessage • Обновлено ${response.updatedAt}"
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                unmappedList.setListData(responseUnmapped.toTypedArray())
                statusLabel.icon = AllIcons.General.InspectionsOK
                statusLabel.text = statusMessage
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Непредвиденная ошибка"
                statusLabel.icon = AllIcons.General.Error
                statusLabel.text = "Сканирование не удалось: $message"
                notify(message, NotificationType.ERROR)
            }
        })
    }

    private fun runGenerateFeature() {
        val projectRoot = projectRootField.text.trim().ifEmpty { project.basePath.orEmpty() }
        if (projectRoot.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Путь к проекту не указан"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }

        val testCaseText = testCaseInput.text.trim()
        if (testCaseText.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Текст тесткейса пустой"
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

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "Генерация feature..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Генерация feature", true) {
            private var featureText: String = ""
            private var usedSteps: List<StepDefinitionDto> = emptyList()
            private var unmapped: List<UnmappedStepDto> = emptyList()

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Отправка тесткейса в сервис..."
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
                val unmappedMessage = if (unmapped.isEmpty()) "" else ", неотображённых: ${unmapped.size}"
                statusLabel.icon = AllIcons.General.InspectionsOK
                statusLabel.text = "Feature сгенерирован. Использовано: ${usedSteps.size}$unmappedMessage"
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Непредвиденная ошибка"
                statusLabel.icon = AllIcons.General.Error
                statusLabel.text = "Генерация не удалась: $message"
                notify(message, NotificationType.ERROR)
            }
        })
    }

    private fun configureStepRenderer(list: JBList<StepDefinitionDto>) {
        list.cellRenderer = object : ColoredListCellRenderer<StepDefinitionDto>() {
            override fun customizeCellRenderer(
                list: javax.swing.JList<out StepDefinitionDto>,
                value: StepDefinitionDto?,
                index: Int,
                selected: Boolean,
                hasFocus: Boolean,
            ) {
                if (value == null) return
                val keywordAttributes = SimpleTextAttributes(SimpleTextAttributes.STYLE_UNDERLINE, JBColor(0x0B874B, 0x7DE390))
                append(value.keyword, keywordAttributes)
                append(" ${value.pattern}")
                value.summary?.takeIf { it.isNotBlank() }?.let {
                    append(" — $it", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                }
            }
        }
    }

    private fun configureUnmappedRenderer(list: JBList<UnmappedStepDto>) {
        list.cellRenderer = object : ColoredListCellRenderer<UnmappedStepDto>() {
            override fun customizeCellRenderer(
                list: javax.swing.JList<out UnmappedStepDto>,
                value: UnmappedStepDto?,
                index: Int,
                selected: Boolean,
                hasFocus: Boolean,
            ) {
                if (value == null) return
                val warningColor = JBColor(0xC77C02, 0xFFB86C)
                val keyword = value.text.substringBefore(' ')
                val rest = value.text.removePrefix(keyword).trimStart()
                append(keyword, SimpleTextAttributes(SimpleTextAttributes.STYLE_UNDERLINE, warningColor))
                if (rest.isNotBlank()) {
                    append(" $rest", SimpleTextAttributes(SimpleTextAttributes.STYLE_PLAIN, warningColor))
                }
                value.reason?.let { append(" — $it", SimpleTextAttributes.GRAYED_ATTRIBUTES) }
            }
        }
    }

    private fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("AI Cucumber Assistant")
            .createNotification(message, type)
            .notify(project)
    }

    private fun buildScanControls(): JPanel {
        val panel = JPanel(GridBagLayout())
        panel.background = JBColor.PanelBackground
        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            weightx = 0.0
            fill = GridBagConstraints.HORIZONTAL
            insets = JBUI.insetsBottom(6)
            anchor = GridBagConstraints.NORTHWEST
        }

        panel.add(JLabel("Корень проекта"), gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(projectRootField, gbc)

        gbc.gridx++
        gbc.weightx = 0.0
        panel.add(scanButton, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.gridwidth = 3
        val hint = JLabel("Укажите путь, который будет передан сервису сканирования.").apply {
            font = font.deriveFont(Font.PLAIN, font.size2D - 1)
            foreground = JBColor.GRAY
        }
        panel.add(hint, gbc)

        return panel
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
        panel.add(JLabel("Язык (необязательно)"), formConstraints)
        formConstraints.gridy++
        panel.add(languageField, formConstraints)

        formConstraints.gridy++
        panel.add(createHintLabel("Оставьте поле пустым для языка по умолчанию"), formConstraints)

        formConstraints.gridy++
        formConstraints.insets = JBUI.insets(12, 0, 0, 0)
        panel.add(generateButton, formConstraints)
        return panel
    }

    private fun createSectionLabel(text: String): JLabel = JLabel(text).apply {
        font = font.deriveFont(Font.BOLD, font.size2D + 1)
        border = JBUI.Borders.emptyBottom(6)
    }

    private fun createHintLabel(text: String): JLabel = JLabel(text).apply {
        font = font.deriveFont(Font.PLAIN, font.size2D - 1)
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

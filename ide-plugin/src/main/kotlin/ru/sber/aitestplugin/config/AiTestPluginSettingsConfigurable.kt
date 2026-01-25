package ru.sber.aitestplugin.config

import com.intellij.icons.AllIcons
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.options.Configurable
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.JBSplitter
import com.intellij.ui.JBColor
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextField
import com.intellij.ui.components.JBPasswordField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.Font
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.ButtonGroup
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JRadioButton

/**
 * Панель настроек плагина (Settings/Preferences → Tools → "AI Test Agent").
 */
class AiTestPluginSettingsConfigurable(
    project: Project? = null,
    backendClient: BackendClient = HttpBackendClient()
) : Configurable {
    private val settingsService = AiTestPluginSettingsService.getInstance()
    private val project: Project = project ?: ProjectManager.getInstance().defaultProject
    private val backendClient: BackendClient = backendClient

    private val projectRootField = JBTextField()
    private val scanButton = JButton("Сканировать шаги", AllIcons.Actions.Search).apply {
        foreground = JBColor(0x0B5CAD, 0x78A6FF)
        background = JBColor(0xE8F1FF, 0x2C3F57)
        border = JBUI.Borders.empty(6, 12)
        isOpaque = true
    }
    private val stepsList = JBList<StepDefinitionDto>()
    private val unmappedList = JBList<UnmappedStepDto>()
    private val statusLabel = JLabel("Индекс ещё не построен", AllIcons.General.Information, JLabel.LEADING)

    private val rootPanel: JPanel = JPanel(BorderLayout(0, JBUI.scale(12)))
    private val zephyrTokenRadio = JRadioButton("Token", true)
    private val zephyrLoginRadio = JRadioButton("Login/Password")
    private val zephyrTokenLabel = JLabel("Token for Jira:")
    private val zephyrTokenField = JBPasswordField()
    private val zephyrLoginLabel = JLabel("Login:")
    private val zephyrLoginField = JBTextField()
    private val zephyrPasswordLabel = JLabel("Password:")
    private val zephyrPasswordField = JBPasswordField()

    constructor(project: Project) : this(project, HttpBackendClient())

    override fun getDisplayName(): String = "AI Test Agent"

    override fun createComponent(): JComponent {
        if (rootPanel.componentCount == 0) {
            buildUi()
        }
        return rootPanel
    }

    override fun isModified(): Boolean {
        val saved = settingsService.settings
        val currentAuthType = if (zephyrTokenRadio.isSelected) ZephyrAuthType.TOKEN else ZephyrAuthType.LOGIN_PASSWORD
        val currentToken = String(zephyrTokenField.password).trim().ifEmpty { null }
        val currentLogin = zephyrLoginField.text.trim().ifEmpty { null }
        val currentPassword = String(zephyrPasswordField.password).trim().ifEmpty { null }
        return projectRootField.text.trim() != (saved.scanProjectRoot ?: "") ||
            currentAuthType != saved.zephyrAuthType ||
            currentToken != saved.zephyrToken ||
            currentLogin != saved.zephyrLogin ||
            currentPassword != saved.zephyrPassword
    }

    override fun apply() {
        settingsService.settings.scanProjectRoot = projectRootField.text.trim().ifEmpty { null }
        settingsService.settings.zephyrAuthType =
            if (zephyrTokenRadio.isSelected) ZephyrAuthType.TOKEN else ZephyrAuthType.LOGIN_PASSWORD
        settingsService.settings.zephyrToken = String(zephyrTokenField.password).trim().ifEmpty { null }
        settingsService.settings.zephyrLogin = zephyrLoginField.text.trim().ifEmpty { null }
        settingsService.settings.zephyrPassword = String(zephyrPasswordField.password).trim().ifEmpty { null }
    }

    override fun reset() {
        val saved = settingsService.settings
        if (rootPanel.componentCount == 0) {
            buildUi()
        }
        projectRootField.text = saved.scanProjectRoot ?: project.basePath.orEmpty()
        zephyrTokenField.text = saved.zephyrToken.orEmpty()
        zephyrLoginField.text = saved.zephyrLogin.orEmpty()
        zephyrPasswordField.text = saved.zephyrPassword.orEmpty()
        if (saved.zephyrAuthType == ZephyrAuthType.TOKEN) {
            zephyrTokenRadio.isSelected = true
        } else {
            zephyrLoginRadio.isSelected = true
        }
        updateZephyrAuthUi()
        loadIndexedSteps(projectRootField.text.trim())
    }

    private fun buildUi() {
        val topPanel = createCardPanel().apply {
            add(sectionLabel("Сканирование шагов"), BorderLayout.NORTH)
            add(buildScanControls(), BorderLayout.CENTER)
        }

        val zephyrPanel = createCardPanel().apply {
            add(sectionLabel("Zephyr"), BorderLayout.NORTH)
            add(buildZephyrControls(), BorderLayout.CENTER)
        }

        stepsList.emptyText.text = "Шаги ещё не найдены"
        unmappedList.emptyText.text = "Неотображённые шаги отсутствуют"
        configureStepRenderer(stepsList)
        configureUnmappedRenderer(unmappedList)

        val stepsPanel = createCardPanel().apply {
            add(sectionLabel("Найденные шаги"), BorderLayout.NORTH)
            add(JBScrollPane(stepsList), BorderLayout.CENTER)
        }

        val unmappedPanel = createCardPanel().apply {
            add(sectionLabel("Неотображённые шаги"), BorderLayout.NORTH)
            add(JBScrollPane(unmappedList), BorderLayout.CENTER)
        }

        val listsSplitter = JBSplitter(false, 0.5f).apply {
            firstComponent = stepsPanel
            secondComponent = unmappedPanel
        }

        val settingsPanel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            background = JBColor.PanelBackground
            add(topPanel)
            add(Box.createVerticalStrut(JBUI.scale(12)))
            add(zephyrPanel)
        }

        rootPanel.add(settingsPanel, BorderLayout.NORTH)
        rootPanel.add(listsSplitter, BorderLayout.CENTER)
        rootPanel.add(statusLabel, BorderLayout.SOUTH)

        scanButton.addActionListener {
            runScanSteps()
        }

        ButtonGroup().apply {
            add(zephyrTokenRadio)
            add(zephyrLoginRadio)
        }
        zephyrTokenRadio.addActionListener { updateZephyrAuthUi() }
        zephyrLoginRadio.addActionListener { updateZephyrAuthUi() }
        updateZephyrAuthUi()
    }

    private fun loadIndexedSteps(projectRoot: String) {
        if (projectRoot.isBlank()) return

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "Загрузка сохранённых шагов..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Загрузка сохранённых шагов", true) {
            private var responseSteps = emptyList<StepDefinitionDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "Обращение к сервису..."
                responseSteps = backendClient.listSteps(projectRoot)
                statusMessage = if (responseSteps.isEmpty()) {
                    "Сохранённые шаги не найдены"
                } else {
                    "Найдено ${responseSteps.size} шагов • Загружено из индекса"
                }
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                unmappedList.setListData(emptyArray())
                statusLabel.icon = AllIcons.General.InspectionsOK
                statusLabel.text = statusMessage
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "Непредвиденная ошибка"
                statusLabel.icon = AllIcons.General.Warning
                statusLabel.text = "Не удалось загрузить индекс: $message"
                notify(message, NotificationType.WARNING)
            }
        })
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

    private fun buildZephyrControls(): JPanel {
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

        panel.add(JLabel("Auth type"), gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        val authPanel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.X_AXIS)
            background = JBColor.PanelBackground
            add(zephyrTokenRadio)
            add(Box.createHorizontalStrut(JBUI.scale(12)))
            add(zephyrLoginRadio)
        }
        panel.add(authPanel, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(zephyrTokenLabel, gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(zephyrTokenField, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(zephyrLoginLabel, gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(zephyrLoginField, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(zephyrPasswordLabel, gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(zephyrPasswordField, gbc)

        return panel
    }

    private fun updateZephyrAuthUi() {
        val tokenSelected = zephyrTokenRadio.isSelected
        setZephyrFieldState(zephyrTokenLabel, zephyrTokenField, tokenSelected)
        setZephyrFieldState(zephyrLoginLabel, zephyrLoginField, !tokenSelected)
        setZephyrFieldState(zephyrPasswordLabel, zephyrPasswordField, !tokenSelected)
        rootPanel.revalidate()
        rootPanel.repaint()
    }

    private fun setZephyrFieldState(label: JLabel, field: JComponent, isVisible: Boolean) {
        label.isVisible = isVisible
        field.isVisible = isVisible
        label.isEnabled = isVisible
        field.isEnabled = isVisible
    }

    private fun runScanSteps() {
        val projectRoot = projectRootField.text.trim()
            .ifEmpty { settingsService.settings.scanProjectRoot.orEmpty() }
            .ifEmpty { project.basePath.orEmpty() }
        if (projectRoot.isBlank()) {
            statusLabel.icon = AllIcons.General.Warning
            statusLabel.text = "Путь к проекту не указан"
            notify("Укажите путь к корню проекта", NotificationType.WARNING)
            return
        }
        settingsService.settings.scanProjectRoot = projectRoot

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

    private fun sectionLabel(text: String): JLabel = JLabel(text).apply {
        font = font.deriveFont(Font.BOLD, font.size2D + 1)
        border = JBUI.Borders.emptyBottom(6)
    }

    private fun createCardPanel(): JPanel = JPanel(BorderLayout()).apply {
        background = JBColor.PanelBackground
        border = JBUI.Borders.compound(
            JBUI.Borders.customLine(JBColor.border(), 1),
            JBUI.Borders.empty(12)
        )
    }
}

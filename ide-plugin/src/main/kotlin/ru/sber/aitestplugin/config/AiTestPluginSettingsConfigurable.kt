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
import com.intellij.openapi.ui.Messages
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
import ru.sber.aitestplugin.util.StepScanRootsResolver
import java.awt.BorderLayout
import java.awt.Font
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.GridLayout
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.ButtonGroup
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JComboBox
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JRadioButton
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64

/**
 * РџР°РЅРµР»СЊ РЅР°СЃС‚СЂРѕРµРє РїР»Р°РіРёРЅР° (Settings/Preferences в†’ Tools в†’ "РђРіРµРЅС‚СѓРј").
 */
class AiTestPluginSettingsConfigurable(
    project: Project? = null,
    backendClient: BackendClient? = null
) : Configurable {
    private val project: Project = project ?: ProjectManager.getInstance().defaultProject
    private val settingsService = AiTestPluginSettingsService.getInstance(this.project)
    private val backendClient: BackendClient = backendClient ?: HttpBackendClient(this.project)

    private val projectRootField = JBTextField()
    private val scanButton = JButton("РЎРєР°РЅРёСЂРѕРІР°С‚СЊ С€Р°РіРё", AllIcons.Actions.Search).apply {
        foreground = JBColor(0x0B5CAD, 0x78A6FF)
        background = JBColor(0xE8F1FF, 0x2C3F57)
        border = JBUI.Borders.empty(6, 12)
        isOpaque = true
    }
    private val stepsList = JBList<StepDefinitionDto>()
    private val statusLabel = JLabel("РРЅРґРµРєСЃ РµС‰С‘ РЅРµ РїРѕСЃС‚СЂРѕРµРЅ", AllIcons.General.Information, JLabel.LEADING)

    private val rootPanel: JPanel = JPanel(BorderLayout(0, JBUI.scale(12)))
    private val zephyrJiraLabel = JLabel("Jira:")
    private val zephyrJiraInstanceCombo = JComboBox(jiraInstanceOptions.keys.toTypedArray())
    private val zephyrTokenRadio = JRadioButton("Token", true)
    private val zephyrLoginRadio = JRadioButton("Login/Password")
    private val zephyrTokenLabel = JLabel("Token for Jira:")
    private val zephyrTokenField = JBPasswordField()
    private val zephyrLoginLabel = JLabel("Login:")
    private val zephyrLoginField = JBTextField()
    private val zephyrPasswordLabel = JLabel("Password:")
    private val zephyrPasswordField = JBPasswordField()
    private val addJiraProjectButton = JButton("Add Jira Project")
    private val verifySettingsButton = JButton("Verify settings")
    private val jiraProjectsPanel = JPanel()
    private val jiraProjects: MutableList<String> = mutableListOf()

    constructor(project: Project) : this(project, HttpBackendClient(project))

    override fun getDisplayName(): String = "РђРіРµРЅС‚СѓРј"

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
        val currentJiraInstanceUrl = resolveJiraInstanceUrl(zephyrJiraInstanceCombo.selectedItem?.toString().orEmpty())
        val savedJiraInstanceUrl = resolveJiraInstanceUrl(saved.zephyrJiraInstance)
        return projectRootField.text.trim() != (saved.scanProjectRoot ?: "") ||
            currentAuthType != saved.zephyrAuthType ||
            currentToken != saved.zephyrToken ||
            currentLogin != saved.zephyrLogin ||
            currentPassword != saved.zephyrPassword ||
            currentJiraInstanceUrl != savedJiraInstanceUrl ||
            jiraProjects != saved.zephyrProjects
    }

    override fun apply() {
        settingsService.settings.scanProjectRoot = projectRootField.text.trim().ifEmpty { null }
        settingsService.settings.zephyrAuthType =
            if (zephyrTokenRadio.isSelected) ZephyrAuthType.TOKEN else ZephyrAuthType.LOGIN_PASSWORD
        settingsService.settings.zephyrToken = String(zephyrTokenField.password).trim().ifEmpty { null }
        settingsService.settings.zephyrLogin = zephyrLoginField.text.trim().ifEmpty { null }
        settingsService.settings.zephyrPassword = String(zephyrPasswordField.password).trim().ifEmpty { null }
        settingsService.settings.zephyrJiraInstance =
            resolveJiraInstanceUrl(zephyrJiraInstanceCombo.selectedItem?.toString().orEmpty()).orEmpty()
        settingsService.settings.zephyrProjects = jiraProjects.toMutableList()
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
        val savedJiraLabel = resolveJiraInstanceLabel(saved.zephyrJiraInstance)
        zephyrJiraInstanceCombo.setSelectedItem(savedJiraLabel)
        jiraProjects.clear()
        jiraProjects.addAll(saved.zephyrProjects)
        refreshJiraProjects()
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
            add(sectionLabel("РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ С€Р°РіРѕРІ"), BorderLayout.NORTH)
            add(buildScanControls(), BorderLayout.CENTER)
        }

        val zephyrPanel = createCardPanel().apply {
            add(sectionLabel("Zephyr"), BorderLayout.NORTH)
            add(buildZephyrControls(), BorderLayout.CENTER)
        }

        stepsList.emptyText.text = "РЁР°РіРё РµС‰С‘ РЅРµ РЅР°Р№РґРµРЅС‹"
        configureStepRenderer(stepsList)

        val stepsPanel = createCardPanel().apply {
            add(sectionLabel("РќР°Р№РґРµРЅРЅС‹Рµ С€Р°РіРё"), BorderLayout.NORTH)
            add(JBScrollPane(stepsList), BorderLayout.CENTER)
        }

        val settingsPanel = JPanel(GridBagLayout()).apply {
            background = JBColor.PanelBackground
            val gbc = GridBagConstraints().apply {
                gridx = 0
                gridy = 0
                weightx = 1.0
                fill = GridBagConstraints.HORIZONTAL
                anchor = GridBagConstraints.NORTHWEST
                insets = JBUI.insetsBottom(12)
            }
            add(topPanel, gbc)
            gbc.gridy++
            gbc.insets = JBUI.emptyInsets()
            add(zephyrPanel, gbc)
            gbc.gridy++
            gbc.weighty = 1.0
            gbc.fill = GridBagConstraints.BOTH
            add(JPanel(GridLayout()), gbc)
        }

        val mainSplitter = JBSplitter(true, 0.62f).apply {
            firstComponent = JBScrollPane(settingsPanel).apply {
                border = JBUI.Borders.empty()
                horizontalScrollBarPolicy = JBScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED
            }
            secondComponent = stepsPanel
        }

        rootPanel.add(mainSplitter, BorderLayout.CENTER)
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
        addJiraProjectButton.addActionListener { promptAddJiraProject() }
        verifySettingsButton.addActionListener { verifyJiraProjectAvailability() }
        updateZephyrAuthUi()
    }

    private fun loadIndexedSteps(projectRoot: String) {
        if (projectRoot.isBlank()) return

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "Р—Р°РіСЂСѓР·РєР° СЃРѕС…СЂР°РЅС‘РЅРЅС‹С… С€Р°РіРѕРІ..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Р—Р°РіСЂСѓР·РєР° СЃРѕС…СЂР°РЅС‘РЅРЅС‹С… С€Р°РіРѕРІ", true) {
            private var responseSteps = emptyList<StepDefinitionDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "РћР±СЂР°С‰РµРЅРёРµ Рє СЃРµСЂРІРёСЃСѓ..."
                responseSteps = backendClient.listSteps(projectRoot)
                statusMessage = if (responseSteps.isEmpty()) {
                    "РЎРѕС…СЂР°РЅС‘РЅРЅС‹Рµ С€Р°РіРё РЅРµ РЅР°Р№РґРµРЅС‹"
                } else {
                    "РќР°Р№РґРµРЅРѕ ${responseSteps.size} С€Р°РіРѕРІ вЂў Р—Р°РіСЂСѓР¶РµРЅРѕ РёР· РёРЅРґРµРєСЃР°"
                }
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                statusLabel.icon = AllIcons.General.InspectionsOK
                statusLabel.text = statusMessage
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "РќРµРїСЂРµРґРІРёРґРµРЅРЅР°СЏ РѕС€РёР±РєР°"
                statusLabel.icon = AllIcons.General.Warning
                statusLabel.text = "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ РёРЅРґРµРєСЃ: $message"
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

        panel.add(JLabel("РљРѕСЂРµРЅСЊ РїСЂРѕРµРєС‚Р°"), gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(projectRootField, gbc)

        gbc.gridx++
        gbc.weightx = 0.0
        panel.add(scanButton, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.gridwidth = 3
        val hint = JLabel("РЈРєР°Р¶РёС‚Рµ РїСѓС‚СЊ, РєРѕС‚РѕСЂС‹Р№ Р±СѓРґРµС‚ РїРµСЂРµРґР°РЅ СЃРµСЂРІРёСЃСѓ СЃРєР°РЅРёСЂРѕРІР°РЅРёСЏ.").apply {
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

        panel.add(zephyrJiraLabel, gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(zephyrJiraInstanceCombo, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(JLabel(""), gbc)
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
        panel.add(JLabel(""), gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(addJiraProjectButton, gbc)

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

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(JLabel("Jira project:"), gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        jiraProjectsPanel.layout = BoxLayout(jiraProjectsPanel, BoxLayout.Y_AXIS)
        jiraProjectsPanel.background = JBColor.PanelBackground
        panel.add(jiraProjectsPanel, gbc)

        gbc.gridx = 0
        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(verifySettingsButton, gbc)
        gbc.gridx++
        gbc.weightx = 1.0
        panel.add(JPanel().apply { background = JBColor.PanelBackground }, gbc)

        refreshJiraProjects()
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

    private fun promptAddJiraProject() {
        val projectKey = Messages.showInputDialog(
            rootPanel,
            "Р’РІРµРґРёС‚Рµ РєР»СЋС‡ Jira РїСЂРѕРµРєС‚Р°",
            "Р”РѕР±Р°РІРёС‚СЊ Jira РїСЂРѕРµРєС‚",
            Messages.getQuestionIcon()
        )?.trim().orEmpty()
        if (projectKey.isBlank()) return
        if (jiraProjects.contains(projectKey)) {
            notify("РџСЂРѕРµРєС‚ СѓР¶Рµ РґРѕР±Р°РІР»РµРЅ", NotificationType.WARNING)
            return
        }
        jiraProjects.add(projectKey)
        refreshJiraProjects()
    }

    private fun refreshJiraProjects() {
        jiraProjectsPanel.removeAll()
        if (jiraProjects.isEmpty()) {
            jiraProjectsPanel.add(JLabel("РЎРїРёСЃРѕРє РїСЂРѕРµРєС‚РѕРІ РїСѓСЃС‚").apply {
                font = font.deriveFont(Font.PLAIN, font.size2D - 1)
                foreground = JBColor.GRAY
            })
        } else {
            jiraProjects.forEach { project ->
                jiraProjectsPanel.add(createProjectRow(project))
                jiraProjectsPanel.add(Box.createVerticalStrut(JBUI.scale(6)))
            }
        }
        jiraProjectsPanel.revalidate()
        jiraProjectsPanel.repaint()
    }

    private fun createProjectRow(projectKey: String): JPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.X_AXIS)
        background = JBColor.PanelBackground
        val projectField = JBTextField(projectKey).apply {
            isEditable = false
        }
        val deleteButton = JButton("Delete").apply {
            addActionListener {
                jiraProjects.remove(projectKey)
                refreshJiraProjects()
            }
        }
        add(projectField)
        add(Box.createHorizontalStrut(JBUI.scale(8)))
        add(deleteButton)
    }

    private fun verifyJiraProjectAvailability() {
        val jiraInstanceName = zephyrJiraInstanceCombo.selectedItem?.toString().orEmpty()
        val jiraBaseUrl = jiraInstanceOptions[jiraInstanceName]
        if (jiraBaseUrl.isNullOrBlank()) {
            notify("РќРµ РІС‹Р±СЂР°РЅ Jira РёРЅСЃС‚Р°РЅСЃ", NotificationType.WARNING)
            return
        }
        val projectKey = jiraProjects.firstOrNull()?.trim().orEmpty()
        if (projectKey.isBlank()) {
            notify("Р”РѕР±Р°РІСЊС‚Рµ Jira РїСЂРѕРµРєС‚ РґР»СЏ РїСЂРѕРІРµСЂРєРё", NotificationType.WARNING)
            return
        }
        val tokenSelected = zephyrTokenRadio.isSelected
        val token = String(zephyrTokenField.password).trim()
        val login = zephyrLoginField.text.trim()
        val password = String(zephyrPasswordField.password).trim()
        if (tokenSelected && token.isBlank()) {
            notify("РЈРєР°Р¶РёС‚Рµ С‚РѕРєРµРЅ Jira", NotificationType.WARNING)
            return
        }
        if (!tokenSelected && (login.isBlank() || password.isBlank())) {
            notify("РЈРєР°Р¶РёС‚Рµ Р»РѕРіРёРЅ Рё РїР°СЂРѕР»СЊ Jira", NotificationType.WARNING)
            return
        }

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "РџСЂРѕРІРµСЂРєР° Jira РїСЂРѕРµРєС‚Р°", true) {
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "РџСЂРѕРІРµСЂСЏРµРј РґРѕСЃС‚СѓРїРЅРѕСЃС‚СЊ РїСЂРѕРµРєС‚Р°..."
                val settings = settingsService.settings
                val requestUrl = "${jiraBaseUrl.trimEnd('/')}/rest/api/2/project/${projectKey.trim()}/"
                val connection = (URL(requestUrl).openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = settings.requestTimeoutMs
                    readTimeout = settings.requestTimeoutMs
                    if (tokenSelected) {
                        setRequestProperty("Authorization", "Bearer $token")
                    } else {
                        val credentials = "$login:$password"
                        val encoded = Base64.getEncoder().encodeToString(credentials.toByteArray(Charsets.UTF_8))
                        setRequestProperty("Authorization", "Basic $encoded")
                    }
                }
                try {
                    val responseCode = connection.responseCode
                    if (responseCode !in 200..299) {
                        val errorBody = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                        val message = errorBody.takeIf { it.isNotBlank() } ?: "HTTP $responseCode"
                        throw IllegalStateException("Jira РѕС‚РІРµС‚РёР»Р° $responseCode: $message")
                    }
                } finally {
                    connection.disconnect()
                }
                statusMessage = "РџСЂРѕРµРєС‚ $projectKey РґРѕСЃС‚СѓРїРµРЅ"
            }

            override fun onSuccess() {
                notify(statusMessage, NotificationType.INFORMATION)
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "РќРµРїСЂРµРґРІРёРґРµРЅРЅР°СЏ РѕС€РёР±РєР°"
                notify("РџСЂРѕРІРµСЂРєР° РЅРµ СѓРґР°Р»Р°СЃСЊ: $message", NotificationType.ERROR)
            }
        })
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
            statusLabel.text = "РџСѓС‚СЊ Рє РїСЂРѕРµРєС‚Сѓ РЅРµ СѓРєР°Р·Р°РЅ"
            notify("РЈРєР°Р¶РёС‚Рµ РїСѓС‚СЊ Рє РєРѕСЂРЅСЋ РїСЂРѕРµРєС‚Р°", NotificationType.WARNING)
            return
        }
        settingsService.settings.scanProjectRoot = projectRoot

        statusLabel.icon = AllIcons.General.BalloonInformation
        statusLabel.text = "РРґС‘С‚ СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ РїСЂРѕРµРєС‚Р°..."

        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ С€Р°РіРѕРІ Cucumber", true) {
            private var responseSteps = emptyList<StepDefinitionDto>()
            private var responseUnmapped = emptyList<UnmappedStepDto>()
            private var statusMessage: String = ""

            override fun run(indicator: ProgressIndicator) {
                indicator.text = "РћР±СЂР°С‰РµРЅРёРµ Рє СЃРµСЂРІРёСЃСѓ..."
                val additionalRoots = StepScanRootsResolver.resolveAdditionalRoots(project, projectRoot)
                val response = backendClient.scanSteps(projectRoot, additionalRoots)
                responseSteps = response.sampleSteps.orEmpty()
                responseUnmapped = response.unmappedSteps
                val unmappedMessage = if (responseUnmapped.isEmpty()) "" else ", РЅРµРѕС‚РѕР±СЂР°Р¶С‘РЅРЅС‹С…: ${responseUnmapped.size}"
                statusMessage = "РќР°Р№РґРµРЅРѕ ${response.stepsCount} С€Р°РіРѕРІ$unmappedMessage вЂў РћР±РЅРѕРІР»РµРЅРѕ ${response.updatedAt}"
            }

            override fun onSuccess() {
                stepsList.setListData(responseSteps.toTypedArray())
                statusLabel.icon = AllIcons.General.InspectionsOK
                statusLabel.text = statusMessage
            }

            override fun onThrowable(error: Throwable) {
                val message = error.message ?: "РќРµРїСЂРµРґРІРёРґРµРЅРЅР°СЏ РѕС€РёР±РєР°"
                statusLabel.icon = AllIcons.General.Error
                statusLabel.text = "РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ РЅРµ СѓРґР°Р»РѕСЃСЊ: $message"
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
                val params = value.parameters.orEmpty()
                if (params.isNotEmpty()) {
                    val signature = params.joinToString(", ") { param ->
                        if (param.type.isNullOrBlank()) param.name else "${param.name}:${param.type}"
                    }
                    append(" [$signature]", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                }
                value.summary?.takeIf { it.isNotBlank() }?.let {
                    append(" вЂ” $it", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                }
            }
        }
    }

    private fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("РђРіРµРЅС‚СѓРј")
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

    companion object {
        private val jiraInstanceOptions = mapOf(
            "Sigma" to "https://jira.sberbank.ru"
        )
    }
}




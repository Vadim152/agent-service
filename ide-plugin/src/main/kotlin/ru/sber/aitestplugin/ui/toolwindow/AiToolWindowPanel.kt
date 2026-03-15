package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.icons.AllIcons
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.popup.JBPopup
import com.intellij.openapi.ui.popup.JBPopupFactory
import com.intellij.openapi.ui.popup.JBPopupListener
import com.intellij.openapi.ui.popup.LightweightWindowEvent
import com.intellij.openapi.ui.popup.PopupStep
import com.intellij.openapi.ui.popup.util.BaseListPopupStep
import com.intellij.ui.JBColor
import com.intellij.ui.awt.RelativePoint
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.concurrency.AppExecutorUtil
import com.intellij.util.ui.JBUI
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import ru.sber.aitestplugin.config.AiTestPluginSettingsConfigurable
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.config.toJiraInstanceUrl
import ru.sber.aitestplugin.config.toZephyrAuthDto
import ru.sber.aitestplugin.model.ChatCommandRequestDto
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatPendingPermissionDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatSessionListItemDto
import ru.sber.aitestplugin.model.ChatSessionStatusResponseDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.OpenCodeCommandExecutionResponseDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import ru.sber.aitestplugin.ui.UiStrings
import ru.sber.aitestplugin.ui.components.StatusBadge
import ru.sber.aitestplugin.ui.theme.PluginUiTheme
import ru.sber.aitestplugin.ui.theme.PluginUiTokens
import ru.sber.aitestplugin.ui.toolwindow.components.ChatComposerPanel
import ru.sber.aitestplugin.ui.toolwindow.components.HistoryPanel
import ru.sber.aitestplugin.ui.toolwindow.components.ToolWindowHeaderPanel
import java.awt.BorderLayout
import java.awt.CardLayout
import java.awt.Color
import java.awt.Component
import java.awt.Cursor
import java.awt.Dimension
import java.awt.FlowLayout
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Insets
import java.awt.RenderingHints
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.BorderFactory
import javax.swing.BoxLayout
import javax.swing.DefaultListCellRenderer
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JCheckBox
import javax.swing.JComboBox
import javax.swing.JList
import javax.swing.JPanel
import javax.swing.SwingUtilities
import javax.swing.Timer
import javax.swing.UIManager
import javax.swing.border.AbstractBorder
import javax.swing.event.DocumentEvent
import javax.swing.event.DocumentListener

class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient(project)
) : JPanel(BorderLayout()) {
    private val logger = Logger.getInstance(AiToolWindowPanel::class.java)
    private val settings = AiTestPluginSettingsService.getInstance(project).settings
    private val openCodeController = OpenCodeAgentCommandController(backendClient)
    private val refreshInFlight = AtomicBoolean(false)
    private val streamClient = OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val pollTimer = Timer(3000) { refreshControlPlaneAsync() }
    private val uiRefreshDebounceMs = 200
    private val autoScrollBottomThresholdPx = 48
    private val maxTraceLines = 30
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault())
    private val sseIndexPattern = Regex("\"index\"\\s*:\\s*(\\d+)")
    private val theme = PluginUiTheme

    private val cardLayout = CardLayout()
    private val bodyCards = JPanel(cardLayout)
    private val timelineLines = mutableListOf<UiLine>()
    private val timelineContainer = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        isOpaque = false
    }
    private val historyModel = DefaultListModel<ChatSessionListItemDto>()
    private val historyList = JBList(historyModel)

    private val inputArea = JBTextArea(4, 20)
    private val sendButton = JButton()
    private val runtimeSelector = JComboBox(RuntimeMode.values())
    private val planModeCheckBox = JCheckBox("Планирование")
    private val statusLabel = JBLabel(UiStrings.connecting)
    private val statusBadge = StatusBadge(UiStrings.connecting, false)
    private val traceToggleButton = JButton()

    private val approvalPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        isOpaque = false
        border = JBUI.Borders.empty(6, 8, 4, 8)
    }
    private val uiApplyTimer = Timer(uiRefreshDebounceMs) { applyPendingUiRefresh() }.apply { isRepeats = false }

    private var selectedRuntime: RuntimeMode = RuntimeMode.CHAT
    private var sessionId: String? = null
    private val sessionIdsByRuntime = mutableMapOf<RuntimeMode, String>()
    private val agentPlanModeBySessionId = mutableMapOf<String, Boolean>()
    private var streamSessionId: String? = null
    private var streamCall: Call? = null
    private var slashPopup: JBPopup? = null
    private var isApplyingSlashSelection: Boolean = false
    private var suppressSlashPopupUntilReset: Boolean = false
    private var lastSlashMatches: List<String> = emptyList()
    private var latestActivity: String = "idle"
    private var latestContextPercent: Int? = null
    private var latestTokenTotal: Int? = null
    private var showAgentTrace: Boolean = true
    private var connectionState: ConnectionState = ConnectionState.CONNECTING
    private var connectionDetails: String? = null
    private var streamReconnectAttempt: Int = 0
    private var streamFromIndex: Int = 0
    private var timelineScrollPane: JBScrollPane? = null
    private var pendingHistoryForRender: ChatHistoryResponseDto? = null
    private var pendingStatusForRender: ChatSessionStatusResponseDto? = null
    private var pendingRefreshSessionId: String? = null
    private var suppressRuntimeSelectionListener: Boolean = false
    @Volatile
    private var initialSessionRequested: Boolean = false
    @Volatile
    private var initialSessionReady: Boolean = false
    @Volatile
    private var forceScrollToBottom: Boolean = false
    private val sessionStateLock = Any()
    private var lastRenderedServerTailKey: String? = null

    init {
        border = JBUI.Borders.empty(8, 8, 10, 8)
        background = theme.panelBackground
        isOpaque = true
        add(buildRoot(), BorderLayout.CENTER)
        updateStatusLabel()
        initialSessionRequested = true
        ensureSessionAsync(forceNew = false)
    }

    override fun addNotify() {
        super.addNotify()
        pollTimer.start()
        sessionId?.let { startEventStreamAsync(it) }
    }

    override fun removeNotify() {
        pollTimer.stop()
        uiApplyTimer.stop()
        pendingHistoryForRender = null
        pendingStatusForRender = null
        stopEventStream()
        suppressSlashPopupUntilReset = false
        lastSlashMatches = emptyList()
        hideSlashPopup()
        super.removeNotify()
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        appendSystemLine("Сканирование завершено: steps=${response.stepsCount}, updated=${response.updatedAt}.")
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        if (unmappedSteps.isNotEmpty()) {
            appendSystemLine("Несопоставленные шаги: ${unmappedSteps.size}")
        }
    }

    private fun buildRoot(): JPanel {
        return JPanel(BorderLayout()).apply {
            isOpaque = true
            background = theme.panelBackground
            add(buildHeader(), BorderLayout.NORTH)
            add(buildBody(), BorderLayout.CENTER)
            add(buildInput(), BorderLayout.SOUTH)
        }
    }

    private fun buildHeader(): JPanel = ToolWindowHeaderPanel(
        title = ToolWindowIds.DISPLAY_NAME,
        statusComponent = statusBadge,
        onNewSession = { ensureSessionAsync(forceNew = true) },
        onShowHistory = {
            showHistoryScreen()
            loadSessionsHistoryAsync()
        },
        onOpenSettings = {
            ShowSettingsUtil.getInstance().showSettingsDialog(
                project,
                AiTestPluginSettingsConfigurable::class.java
            )
        }
    )

    private fun buildBody(): JPanel {
        bodyCards.isOpaque = false
        bodyCards.add(buildChatCard(), "chat")
        bodyCards.add(buildHistoryCard(), "history")
        cardLayout.show(bodyCards, "chat")
        return bodyCards
    }

    private fun buildChatCard(): JPanel {
        val timelineViewport = JPanel(BorderLayout()).apply {
            isOpaque = false
            add(timelineContainer, BorderLayout.NORTH)
        }
        val traceControls = JPanel(FlowLayout(FlowLayout.RIGHT, 8, 2)).apply {
            isOpaque = false
            add(traceToggleButton.apply {
                cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                foreground = theme.secondaryText
                background = theme.controlBackground
                border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
                isContentAreaFilled = true
                isFocusPainted = false
                addActionListener {
                    showAgentTrace = !showAgentTrace
                    updateTraceToggleState()
                    renderTimeline()
                }
            })
        }
        val footer = JPanel(BorderLayout()).apply {
            isOpaque = false
            add(traceControls, BorderLayout.NORTH)
            add(approvalPanel, BorderLayout.CENTER)
        }
        updateTraceToggleState()
        renderTimeline()

        return JPanel(BorderLayout()).apply {
            isOpaque = false
            add(JBScrollPane(timelineViewport).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty(2)
                )
                background = theme.panelBackground
                viewport.background = theme.panelBackground
                preferredSize = Dimension(100, PluginUiTokens.toolWindowMinTimelineHeight)
                viewport.addComponentListener(object : java.awt.event.ComponentAdapter() {
                    override fun componentResized(e: java.awt.event.ComponentEvent?) {
                        renderTimeline()
                    }
                })
                timelineScrollPane = this
            }, BorderLayout.CENTER)
            add(footer, BorderLayout.SOUTH)
        }
    }

    private fun buildHistoryCard(): JPanel {
        historyList.cellRenderer = SessionRenderer(timeFormatter)
        historyList.background = theme.containerBackground
        historyList.foreground = theme.primaryText
        historyList.selectionBackground = theme.controlBackground
        historyList.selectionForeground = theme.primaryText
        historyList.emptyText.text = UiStrings.noChatsYet
        historyList.addMouseListener(object : java.awt.event.MouseAdapter() {
            override fun mouseClicked(e: java.awt.event.MouseEvent) {
                if (e.clickCount >= 2) {
                    historyList.selectedValue?.let { activateSession(it) }
                }
            }
        })

        return HistoryPanel(
            historyList = historyList,
            onBack = { showChatScreen() },
            onOpenSelected = { historyList.selectedValue?.let { activateSession(it) } }
        )
    }

    private fun buildInput(): JPanel {
        inputArea.lineWrap = true
        inputArea.wrapStyleWord = true
        inputArea.background = theme.inputBackground
        inputArea.foreground = theme.primaryText
        inputArea.caretColor = theme.primaryText
        inputArea.border = JBUI.Borders.empty(4, 6)
        inputArea.font = inputArea.font.deriveFont(14f)
        inputArea.putClientProperty("JTextArea.placeholderText", UiStrings.chatInputPlaceholder)
        inputArea.document.addDocumentListener(object : DocumentListener {
            override fun insertUpdate(e: DocumentEvent?) = maybeShowSlashPopup()
            override fun removeUpdate(e: DocumentEvent?) = maybeShowSlashPopup()
            override fun changedUpdate(e: DocumentEvent?) = maybeShowSlashPopup()
        })
        inputArea.addKeyListener(object : java.awt.event.KeyAdapter() {
            override fun keyPressed(e: java.awt.event.KeyEvent) {
                if (e.keyCode == java.awt.event.KeyEvent.VK_ENTER && !e.isShiftDown) {
                    e.consume()
                    onSendOrStop()
                }
            }
        })

        sendButton.cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        sendButton.preferredSize = Dimension(42, 34)
        sendButton.border = RoundedLineBorder(theme.controlBorder, 1, 14)
        sendButton.isBorderPainted = true
        sendButton.isFocusPainted = false
        sendButton.isContentAreaFilled = true
        sendButton.addActionListener { onSendOrStop() }
        updateSendButtonState()

        runtimeSelector.selectedItem = selectedRuntime
        runtimeSelector.toolTipText = UiStrings.runtimeLabel
        runtimeSelector.background = theme.controlBackground
        runtimeSelector.foreground = theme.primaryText
        runtimeSelector.border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
        runtimeSelector.renderer = RuntimeModeRenderer()
        runtimeSelector.addActionListener {
            val target = runtimeSelector.selectedItem as? RuntimeMode ?: return@addActionListener
            if (!shouldProcessRuntimeSelectionChange(suppressRuntimeSelectionListener, target, selectedRuntime)) {
                return@addActionListener
            }
            selectedRuntime = target
            sessionId = sessionIdsByRuntime[target]
            latestActivity = "idle"
            connectionDetails = null
            syncPlanModeCheckboxFromSession()
            updateStatusLabel()
            ensureSessionAsync(forceNew = false)
            if (target == RuntimeMode.AGENT) {
                refreshOpenCodeCatalogAsync()
            }
        }

        planModeCheckBox.isOpaque = false
        planModeCheckBox.foreground = theme.secondaryText
        planModeCheckBox.isVisible = selectedRuntime == RuntimeMode.AGENT
        planModeCheckBox.addActionListener {
            persistPlanModeState(planModeCheckBox.isSelected)
            updateStatusLabel()
        }

        statusLabel.foreground = theme.secondaryText
        statusLabel.border = JBUI.Borders.empty(6, 6, 0, 6)
        val controls = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0)).apply {
            isOpaque = false
            add(planModeCheckBox)
        }
        syncPlanModeCheckboxFromSession()
        return ChatComposerPanel(runtimeSelector, inputArea, sendButton, statusLabel, controls)
    }

    private fun onSendOrStop() {
        if (isGenerating()) {
            submitCommand("abort")
        } else {
            submitInput(inputArea.text.trim())
        }
    }

    private fun submitInput(input: String) {
        if (input.isBlank()) return
        if (selectedRuntime == RuntimeMode.AGENT && OpenCodeAgentCommandController.parseSlashInput(input) != null) {
            submitOpenCodeSlashCommand(input)
            return
        }
        submitMessage(input)
    }

    private fun submitMessage(message: String) {
        if (isGenerating()) {
            appendSystemLine("\u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u044f \u0442\u0435\u043a\u0443\u0449\u0435\u0433\u043e \u043e\u0442\u0432\u0435\u0442\u0430.")
            return
        }
        latestActivity = "busy"
        upsertProgressLine("\u0418\u0434\u0451\u0442 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430...")
        updateSendButtonState()
        updateStatusLabel()
        ApplicationManager.getApplication().executeOnPooledThread {
            val requireFreshSession = sessionId.isNullOrBlank() || (initialSessionRequested && !initialSessionReady)
            val active = ensureSessionBlocking(forceNew = requireFreshSession)
            if (active == null) {
                SwingUtilities.invokeLater {
                    latestActivity = "idle"
                    removeProgressLine()
                    updateSendButtonState()
                    updateStatusLabel()
                }
                return@executeOnPooledThread
            }
            try {
                val request = if (selectedRuntime == RuntimeMode.AGENT) {
                    ChatMessageRequestDto(
                        content = message,
                        displayText = message,
                        metadata = buildAgentMessageMetadata()
                    )
                } else {
                    ChatMessageRequestDto(content = message)
                }
                backendClient.sendChatMessage(active, request)
                SwingUtilities.invokeLater {
                    inputArea.text = ""
                    suppressSlashPopupUntilReset = false
                    hideSlashPopup()
                    forceScrollToBottom = true
                    scrollToBottomIfNeeded(true)
                    setConnectionState(ConnectionState.CONNECTED)
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to send chat message", ex)
                SwingUtilities.invokeLater {
                    latestActivity = "idle"
                    removeProgressLine()
                    updateSendButtonState()
                    updateStatusLabel()
                    appendSystemLine("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435: ${ex.message}")
                }
            }
        }
    }

    private fun submitCommand(command: String) {
        val active = sessionId ?: return
        appendSystemLine("/$command")
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                backendClient.executeChatCommand(active, ChatCommandRequestDto(command = command))
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to execute command", ex)
                SwingUtilities.invokeLater { appendSystemLine("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443: ${ex.message}") }
            }
        }
    }

    private fun submitOpenCodeSlashCommand(input: String) {
        if (isGenerating()) {
            appendSystemLine("Дождитесь завершения текущего ответа.")
            return
        }
        latestActivity = "busy"
        upsertProgressLine("Выполняется OpenCode команда...")
        updateSendButtonState()
        updateStatusLabel()
        ApplicationManager.getApplication().executeOnPooledThread {
            val projectRoot = currentRuntimeProjectRoot(selectedRuntime)
            try {
                val response = openCodeController.executeSlashCommand(
                    sessionId = sessionId,
                    projectRoot = projectRoot,
                    input = input,
                    messageMetadata = buildAgentMessageMetadata()
                )
                SwingUtilities.invokeLater {
                    inputArea.text = ""
                    suppressSlashPopupUntilReset = false
                    hideSlashPopup()
                    forceScrollToBottom = true
                    handleOpenCodeExecutionResponse(response)
                    setConnectionState(ConnectionState.CONNECTED)
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to execute OpenCode command", ex)
                SwingUtilities.invokeLater {
                    latestActivity = "idle"
                    removeProgressLine()
                    updateSendButtonState()
                    updateStatusLabel()
                    appendSystemLine("Не удалось выполнить OpenCode команду: ${ex.message}")
                }
            }
        }
    }

    private fun ensureSessionAsync(forceNew: Boolean) {
        if (forceNew) {
            initialSessionRequested = true
            initialSessionReady = false
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            val active = ensureSessionBlocking(forceNew) ?: return@executeOnPooledThread
            SwingUtilities.invokeLater {
                showChatScreen()
                setConnectionState(ConnectionState.CONNECTING, "\u0421\u0435\u0441\u0441\u0438\u044f ${active.take(8)}")
            }
            startEventStreamAsync(active)
            refreshOpenCodeCatalogAsync()
            refreshControlPlaneAsync()
        }
    }

    private fun currentRuntimeProjectRoot(mode: RuntimeMode): String {
        return resolveRuntimeProjectRootValue(mode.backendValue, project.basePath)
    }

    private fun currentPlanModeEnabled(): Boolean =
        selectedRuntime == RuntimeMode.AGENT && planModeCheckBox.isSelected

    private fun persistPlanModeState(enabled: Boolean) {
        if (selectedRuntime != RuntimeMode.AGENT) return
        sessionId?.takeIf { it.isNotBlank() }?.let { activeSession ->
            agentPlanModeBySessionId[activeSession] = enabled
        }
    }

    private fun syncPlanModeCheckboxFromSession() {
        planModeCheckBox.isVisible = selectedRuntime == RuntimeMode.AGENT
        val selected = sessionId?.let { agentPlanModeBySessionId[it] } ?: false
        if (planModeCheckBox.isSelected != selected) {
            planModeCheckBox.isSelected = selected
        }
    }

    private fun buildAgentMessageMetadata(): Map<String, Any?> {
        val metadata = linkedMapOf<String, Any?>()
        if (currentPlanModeEnabled()) {
            metadata["planMode"] = true
        }
        return metadata
    }

    private fun ensureSessionBlocking(forceNew: Boolean): String? {
        synchronized(sessionStateLock) {
            if (!forceNew) {
                val existing = sessionIdsByRuntime[selectedRuntime]
                if (!existing.isNullOrBlank()) {
                    sessionId = existing
                    initialSessionReady = true
                    return existing
                }
            }
            if (!forceNew && !sessionId.isNullOrBlank()) {
                initialSessionReady = true
                return sessionId
            }
            if (forceNew) {
                initialSessionRequested = true
                initialSessionReady = false
            }

            val projectRoot = currentRuntimeProjectRoot(selectedRuntime)
            if (projectRoot.isBlank()) {
                SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "\u041a\u043e\u0440\u0435\u043d\u044c \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d") }
                return null
            }

            return try {
                val created = backendClient.createChatSession(
                    ChatSessionCreateRequestDto(
                        projectRoot = projectRoot,
                        source = "ide-plugin",
                        profile = selectedRuntime.defaultProfile,
                        runtime = selectedRuntime.backendValue,
                        reuseExisting = !forceNew,
                        zephyrAuth = settings.toZephyrAuthDto(),
                        jiraInstance = settings.toJiraInstanceUrl()
                    )
                )
                sessionId = created.sessionId
                sessionIdsByRuntime[selectedRuntime] = created.sessionId
                syncPlanModeCheckboxFromSession()
                latestActivity = "idle"
                streamReconnectAttempt = 0
                streamFromIndex = 0
                initialSessionReady = true
                if (forceNew || !created.reused) {
                    SwingUtilities.invokeLater {
                        uiApplyTimer.stop()
                        clearPendingUiRefresh()
                        forceScrollToBottom = false
                        timelineLines.clear()
                        lastRenderedServerTailKey = null
                        renderTimeline()
                        renderPendingApprovals(emptyList(), null)
                    }
                }
                created.sessionId
            } catch (ex: Exception) {
                if (forceNew) {
                    initialSessionReady = false
                }
                logger.warn("Failed to create session", ex)
                SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "\u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438: ${ex.message}") }
                null
            }
        }
    }

    private fun activateSession(targetSession: ChatSessionListItemDto) {
        selectedRuntime = runtimeModeFromBackend(targetSession.runtime)
        suppressRuntimeSelectionListener = true
        try {
            runtimeSelector.selectedItem = selectedRuntime
        } finally {
            suppressRuntimeSelectionListener = false
        }
        sessionId = targetSession.sessionId
        sessionIdsByRuntime[selectedRuntime] = targetSession.sessionId
        syncPlanModeCheckboxFromSession()
        initialSessionRequested = true
        initialSessionReady = true
        latestActivity = "idle"
        forceScrollToBottom = false
        uiApplyTimer.stop()
        clearPendingUiRefresh()
        timelineLines.clear()
        lastRenderedServerTailKey = null
        renderTimeline()
        renderPendingApprovals(emptyList(), null)
        streamReconnectAttempt = 0
        streamFromIndex = 0
        showChatScreen()
        startEventStreamAsync(targetSession.sessionId)
        refreshControlPlaneAsync()
    }

    private fun loadSessionsHistoryAsync() {
        val projectRoot = currentRuntimeProjectRoot(selectedRuntime)
        if (projectRoot.isBlank()) {
            setConnectionState(ConnectionState.OFFLINE, "\u041a\u043e\u0440\u0435\u043d\u044c \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d")
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val result = backendClient.listChatSessions(projectRoot, 100)
                SwingUtilities.invokeLater {
                    historyModel.clear()
                    result.items.forEach(historyModel::addElement)
                }
            } catch (ex: Exception) {
                logger.warn("Failed to load sessions", ex)
                SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0438\u0441\u0442\u043e\u0440\u0438\u044e") }
            }
        }
    }

    private fun refreshControlPlaneAsync() {
        val active = sessionId ?: return
        if (!refreshInFlight.compareAndSet(false, true)) return

        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val history = backendClient.getChatHistory(active)
                val status = backendClient.getChatStatus(active)
                SwingUtilities.invokeLater {
                    enqueueUiRefresh(active, history, status)
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) logger.debug("Refresh failed", ex)
            } finally {
                refreshInFlight.set(false)
            }
        }
    }

    private fun enqueueUiRefresh(
        requestedSessionId: String,
        history: ChatHistoryResponseDto,
        status: ChatSessionStatusResponseDto
    ) {
        if (!shouldApplyUiRefresh(requestedSessionId, history.sessionId, status.sessionId, sessionId)) {
            return
        }
        pendingRefreshSessionId = requestedSessionId
        pendingHistoryForRender = history
        pendingStatusForRender = status
        uiApplyTimer.restart()
    }

    private fun applyPendingUiRefresh() {
        val requestedSessionId = pendingRefreshSessionId ?: return
        val history = pendingHistoryForRender ?: return
        val status = pendingStatusForRender ?: return
        if (!shouldApplyUiRefresh(requestedSessionId, history.sessionId, status.sessionId, sessionId)) {
            clearPendingUiRefresh()
            return
        }
        clearPendingUiRefresh()
        renderHistory(history)
        renderStatus(status)
    }

    private fun renderHistory(history: ChatHistoryResponseDto) {
        val shouldStickToBottom = forceScrollToBottom || isUserNearBottom()
        val seenMessageKeys = mutableSetOf<String>()
        val serverLines = history.messages
            .filterNot { it.role.equals("assistant", ignoreCase = true) && it.content.trim().isBlank() }
            .sortedBy { it.createdAt }
            .filter { message ->
                val key = message.messageId.ifBlank {
                    "${message.role}:${message.createdAt.toEpochMilli()}:${message.content.hashCode()}"
                }
                seenMessageKeys.add(key)
            }
            .map { message ->
                val lineKind = when (message.role.lowercase()) {
                    "user" -> UiLineKind.USER
                    "assistant" -> if (message.metadata["question"] == true) UiLineKind.QUESTION else UiLineKind.ASSISTANT
                    else -> UiLineKind.SYSTEM
                }
                val stableKey = message.messageId.ifBlank {
                    "${message.role}:${message.createdAt.toEpochMilli()}:${message.content.hashCode()}"
                }
                UiLine(
                    kind = lineKind,
                    text = message.content,
                    createdAt = message.createdAt,
                    stableKey = stableKey,
                    source = UiLineSource.SERVER_MESSAGE
                )
            }
        val eventTraceLines = if (history.runtime.equals("opencode", ignoreCase = true)) {
            AgentEventLogFormatter.buildAgentEventLines(history.events, maxTraceLines)
                .map { event ->
                    UiLine(
                        kind = UiLineKind.AGENT_EVENT,
                        text = event.text,
                        createdAt = event.createdAt,
                        stableKey = event.stableKey,
                        source = UiLineSource.SERVER_EVENT
                    )
                }
        } else {
            emptyList()
        }
        val questionKeys = serverLines.filter { it.kind == UiLineKind.QUESTION }.mapTo(linkedSetOf()) { it.stableKey }

        val localLines = timelineLines.filter { it.source == UiLineSource.LOCAL_SYSTEM }
        val progressLine = timelineLines.firstOrNull { it.source == UiLineSource.PROGRESS }
        val mergedServerTimeline = if (history.runtime.equals("opencode", ignoreCase = true)) {
            AgentEventLogFormatter.mergeConversationAndEvents(
                messages = serverLines.map { line ->
                    AgentEventLogFormatter.TimelineItem(
                        kind = when (line.kind) {
                            UiLineKind.USER -> AgentEventLogFormatter.TimelineKind.USER
                            UiLineKind.ASSISTANT -> AgentEventLogFormatter.TimelineKind.ASSISTANT
                            UiLineKind.QUESTION -> AgentEventLogFormatter.TimelineKind.ASSISTANT
                            UiLineKind.SYSTEM -> AgentEventLogFormatter.TimelineKind.SYSTEM
                            UiLineKind.PROGRESS, UiLineKind.AGENT_EVENT -> AgentEventLogFormatter.TimelineKind.AGENT_EVENT
                        },
                        text = line.text,
                        createdAt = line.createdAt,
                        stableKey = line.stableKey
                    )
                },
                events = eventTraceLines.map { line ->
                    AgentEventLogFormatter.TimelineItem(
                        kind = AgentEventLogFormatter.TimelineKind.AGENT_EVENT,
                        text = line.text,
                        createdAt = line.createdAt,
                        stableKey = line.stableKey
                    )
                }
            ).map { item ->
                UiLine(
                    kind = when (item.kind) {
                        AgentEventLogFormatter.TimelineKind.USER -> UiLineKind.USER
                        AgentEventLogFormatter.TimelineKind.ASSISTANT -> if (item.stableKey in questionKeys) UiLineKind.QUESTION else UiLineKind.ASSISTANT
                        AgentEventLogFormatter.TimelineKind.SYSTEM -> UiLineKind.SYSTEM
                        AgentEventLogFormatter.TimelineKind.AGENT_EVENT -> UiLineKind.AGENT_EVENT
                    },
                    text = item.text,
                    createdAt = item.createdAt,
                    stableKey = item.stableKey,
                    source = if (item.kind == AgentEventLogFormatter.TimelineKind.AGENT_EVENT) UiLineSource.SERVER_EVENT else UiLineSource.SERVER_MESSAGE
                )
            }
        } else {
            serverLines
        }

        val targetLines = buildList {
            addAll(mergedServerTimeline)
            addAll(localLines)
            progressLine?.let { add(it) }
        }
        replaceTimelineModelIncrementally(targetLines)
        renderPendingApprovals(history.pendingPermissions, extractLatestPendingQuestion(history.messages))
        scrollToBottomIfNeeded(shouldStickToBottom)
        val currentTailKey = serverLines.lastOrNull()?.stableKey
        if (forceScrollToBottom && currentTailKey != null && currentTailKey != lastRenderedServerTailKey) {
            forceScrollToBottom = false
        }
        if (currentTailKey != null) {
            lastRenderedServerTailKey = currentTailKey
        }
    }

    private fun renderStatus(status: ChatSessionStatusResponseDto) {
        latestActivity = status.activity.lowercase()
        selectedRuntime = runtimeModeFromBackend(status.runtime)
        if (selectedRuntime == RuntimeMode.AGENT) {
            latestContextPercent = resolveContextPercent(
                percent = status.limits.percent,
                used = status.limits.used,
                contextWindow = status.limits.contextWindow
            )
            latestTokenTotal = opencodeCliTokenTotal(
                input = status.totals.tokens.input,
                output = status.totals.tokens.output,
                reasoning = status.totals.tokens.reasoning
            )
        } else {
            latestContextPercent = null
            latestTokenTotal = null
        }
        runtimeSelector.selectedItem = selectedRuntime
        syncPlanModeCheckboxFromSession()
        updateTraceToggleState()
        updateSendButtonState()

        val progress = AgentEventLogFormatter.formatPhaseProgress(
            activity = latestActivity,
            currentAction = status.currentAction,
            retryMessage = status.lastRetryMessage
        )
        if (progress != null) {
            upsertProgressLine(progress)
        } else {
            removeProgressLine()
        }
        updateStatusLabel()
    }

    private fun renderPendingApprovals(
        pending: List<ChatPendingPermissionDto>,
        questionCard: AgentQuestionCard?
    ) {
        approvalPanel.removeAll()
        pending.forEach { permission ->
            val row = JPanel(BorderLayout()).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty(8)
                )
                background = theme.containerBackground
                isOpaque = true
            }
            row.add(JBLabel("\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435: ${permission.title} (${permission.kind})").apply {
                foreground = theme.primaryText
            }, BorderLayout.CENTER)
            row.add(JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                isOpaque = false
                add(actionButton("\u0420\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044c \u043e\u0434\u0438\u043d \u0440\u0430\u0437") { submitApproval(permission, "approve_once") })
                add(actionButton("\u0420\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u044c \u0432\u0441\u0435\u0433\u0434\u0430") { submitApproval(permission, "approve_always") })
                add(actionButton("\u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c") { submitApproval(permission, "reject") })
            }, BorderLayout.EAST)
            approvalPanel.add(row)
        }
        questionCard?.let { question ->
            val row = JPanel(BorderLayout()).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty(8)
                )
                background = theme.containerBackground
                isOpaque = true
            }
            row.add(
                JBLabel(question.title).apply {
                    foreground = theme.primaryText
                },
                BorderLayout.CENTER
            )
            row.add(
                JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                    isOpaque = false
                    val buttonChoices = if (question.kind == "plan_confirmation") {
                        listOf("Продолжить", "Уточнить план")
                    } else {
                        question.choices
                    }
                    buttonChoices.forEach { choice ->
                        add(actionButton(choice) { submitMessage(choice) })
                    }
                    if (question.allowCustomAnswer) {
                        add(actionButton("Свой вариант") { inputArea.requestFocusInWindow() })
                    }
                },
                BorderLayout.EAST
            )
            approvalPanel.add(row)
        }
        approvalPanel.revalidate()
        approvalPanel.repaint()
    }

    private fun submitApproval(permission: ChatPendingPermissionDto, decision: String) {
        val active = sessionId ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                backendClient.submitChatToolDecision(
                    active,
                    ChatToolDecisionRequestDto(permissionId = permission.permissionId, decision = decision)
                )
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to submit decision", ex)
                SwingUtilities.invokeLater { appendSystemLine("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0440\u0435\u0448\u0435\u043d\u0438\u0435: ${ex.message}") }
            }
        }
    }

    private fun startEventStreamAsync(activeSession: String) {
        if (streamSessionId == activeSession && streamCall != null) return
        stopEventStream()
        streamSessionId = activeSession
        setConnectionState(ConnectionState.CONNECTING)

        ApplicationManager.getApplication().executeOnPooledThread {
            val base = settings.backendUrl.trimEnd('/')
            val request = Request.Builder().url("$base/sessions/$activeSession/stream?fromIndex=$streamFromIndex").get().build()
            val call = streamClient.newCall(request)
            streamCall = call
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) {
                        setConnectionState(ConnectionState.RECONNECTING, "HTTP ${response.code}")
                        scheduleStreamReconnect(activeSession, "HTTP ${response.code}")
                        return@use
                    }
                    streamReconnectAttempt = 0
                    setConnectionState(ConnectionState.CONNECTED)
                    val source = response.body?.source() ?: run {
                        setConnectionState(ConnectionState.RECONNECTING, "\u041f\u0443\u0441\u0442\u043e\u0435 \u0442\u0435\u043b\u043e \u043e\u0442\u0432\u0435\u0442\u0430")
                        scheduleStreamReconnect(activeSession, "\u043f\u0443\u0441\u0442\u043e\u0439 \u043e\u0442\u0432\u0435\u0442")
                        return@use
                    }
                    var hasData = false
                    while (!source.exhausted() && isDisplayable && sessionId == activeSession) {
                        val line = source.readUtf8Line() ?: break
                        when {
                            line.startsWith("data:") -> {
                                hasData = true
                                updateStreamIndexFromLine(line)
                            }
                            line.isBlank() && hasData -> {
                                hasData = false
                                refreshControlPlaneAsync()
                            }
                        }
                    }
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) logger.debug("Stream disconnected", ex)
                setConnectionState(ConnectionState.RECONNECTING, ex.message ?: "\u041f\u043e\u0442\u043e\u043a \u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d")
                scheduleStreamReconnect(activeSession, ex.message ?: "отключено")
            } finally {
                if (streamCall == call) streamCall = null
            }
        }
    }

    private fun scheduleStreamReconnect(activeSession: String, reason: String) {
        if (!isDisplayable || sessionId != activeSession) return
        val exponent = minOf(streamReconnectAttempt, 5)
        val delayMs = minOf(30_000L, 1200L * (1L shl exponent))
        streamReconnectAttempt = minOf(streamReconnectAttempt + 1, 10)
        setConnectionState(ConnectionState.RECONNECTING, "\u041f\u0435\u0440\u0435\u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u0447\u0435\u0440\u0435\u0437 ${delayMs}ms ($reason)")
        AppExecutorUtil.getAppScheduledExecutorService().schedule(
            {
                if (isDisplayable && sessionId == activeSession) {
                    startEventStreamAsync(activeSession)
                }
            },
            delayMs,
            TimeUnit.MILLISECONDS
        )
    }

    private fun stopEventStream() {
        streamCall?.cancel()
        streamCall = null
        streamSessionId = null
        setConnectionState(ConnectionState.OFFLINE)
    }

    private fun showHistoryScreen() {
        hideSlashPopup()
        cardLayout.show(bodyCards, "history")
    }

    private fun showChatScreen() {
        cardLayout.show(bodyCards, "chat")
    }

    private fun isGenerating(): Boolean = latestActivity in setOf("busy", "retry", "waiting_permission")

    private fun updateSendButtonState() {
        if (isGenerating()) {
            sendButton.text = ""
            sendButton.icon = AllIcons.Actions.Close
            sendButton.background = theme.stopButtonBackground
            sendButton.foreground = JBColor.WHITE
        } else {
            sendButton.text = ""
            sendButton.icon = AllIcons.Actions.Execute
            sendButton.background = theme.sendButtonBackground
            sendButton.foreground = JBColor.WHITE
        }
        sendButton.toolTipText = if (isGenerating()) "\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u044e" else "\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435"
        sendButton.isOpaque = true
    }

    private fun setConnectionState(state: ConnectionState, details: String? = null) {
        connectionState = state
        if (!details.isNullOrBlank()) {
            connectionDetails = details
        } else if (state == ConnectionState.CONNECTED || state == ConnectionState.OFFLINE) {
            connectionDetails = null
        }
        updateStatusLabel()
    }

    private fun updateStatusLabel() {
        val runtimeText = selectedRuntime.title
        val activityText = when (latestActivity) {
            "busy" -> UiStrings.statusBusy
            "retry" -> UiStrings.statusRetry
            "waiting_permission" -> UiStrings.statusWaitingApproval
            "waiting_input" -> "Ожидание ответа"
            "error" -> UiStrings.statusError
            else -> UiStrings.statusIdle
        }
        val connectionText = when (connectionState) {
            ConnectionState.CONNECTING -> UiStrings.statusConnecting
            ConnectionState.CONNECTED -> UiStrings.statusOnline
            ConnectionState.RECONNECTING -> UiStrings.statusReconnecting
            ConnectionState.OFFLINE -> UiStrings.statusOffline
        }
        val text = buildStatusLabelText(
            runtimeText = runtimeText,
            activityText = activityText,
            connectionText = connectionText,
            details = buildStatusDetails(connectionDetails, currentPlanModeEnabled()),
            contextPercent = latestContextPercent.takeIf { selectedRuntime == RuntimeMode.AGENT },
            tokenTotal = latestTokenTotal.takeIf { selectedRuntime == RuntimeMode.AGENT }
        )
        val online = connectionState == ConnectionState.CONNECTED
        if (SwingUtilities.isEventDispatchThread()) {
            statusLabel.text = text
            statusBadge.update(connectionText.replaceFirstChar(Char::uppercase), online)
        } else {
            SwingUtilities.invokeLater {
                statusLabel.text = text
                statusBadge.update(connectionText.replaceFirstChar(Char::uppercase), online)
            }
        }
    }

    private fun updateStreamIndexFromLine(line: String) {
        val payload = line.removePrefix("data:").trim()
        val match = sseIndexPattern.find(payload) ?: return
        val parsed = match.groupValues.getOrNull(1)?.toIntOrNull() ?: return
        streamFromIndex = maxOf(streamFromIndex, parsed + 1)
    }

    private fun appendSystemLine(text: String) {
        val shouldStickToBottom = isUserNearBottom()
        timelineLines.add(
            UiLine(
                kind = UiLineKind.SYSTEM,
                text = text,
                createdAt = Instant.now(),
                stableKey = "local-system-${System.nanoTime()}",
                source = UiLineSource.LOCAL_SYSTEM
            )
        )
        renderTimeline()
        scrollToBottomIfNeeded(shouldStickToBottom)
    }

    private fun clearPendingUiRefresh() {
        pendingRefreshSessionId = null
        pendingHistoryForRender = null
        pendingStatusForRender = null
    }

    private fun upsertProgressLine(text: String) {
        val shouldStickToBottom = isUserNearBottom()
        val idx = timelineLines.indexOfFirst { it.source == UiLineSource.PROGRESS }.takeIf { it >= 0 }
        if (idx == null) {
            timelineLines.add(
                UiLine(
                    kind = UiLineKind.PROGRESS,
                    text = text,
                    createdAt = Instant.now(),
                    stableKey = "progress",
                    source = UiLineSource.PROGRESS
                )
            )
        } else {
            val existing = timelineLines[idx]
            if (existing.text != text) {
                timelineLines[idx] = existing.copy(text = text, createdAt = Instant.now())
            }
        }
        renderTimeline()
        scrollToBottomIfNeeded(shouldStickToBottom)
    }

    private fun removeProgressLine() {
        val idx = timelineLines.indexOfFirst { it.source == UiLineSource.PROGRESS }
        if (idx < 0) return
        timelineLines.removeAt(idx)
        renderTimeline()
    }

    private fun replaceTimelineModelIncrementally(target: List<UiLine>) {
        if (timelineLines == target) return
        timelineLines.clear()
        timelineLines.addAll(target)
        renderTimeline()
    }

    private fun isUserNearBottom(): Boolean {
        val scrollPane = timelineScrollPane ?: return true
        val viewport = scrollPane.viewport ?: return true
        val view = viewport.view ?: return true
        val viewHeight = view.preferredSize.height
        if (viewHeight <= 0) return true
        val bottomY = viewport.viewPosition.y + viewport.extentSize.height
        return bottomY >= viewHeight - autoScrollBottomThresholdPx
    }

    private fun scrollToBottomIfNeeded(shouldStickToBottom: Boolean) {
        if (!shouldStickToBottom) return
        SwingUtilities.invokeLater {
            val scrollBar = timelineScrollPane?.verticalScrollBar ?: return@invokeLater
            scrollBar.value = scrollBar.maximum - scrollBar.visibleAmount
        }
    }

    private fun maybeShowSlashPopup() {
        if (isApplyingSlashSelection) {
            isApplyingSlashSelection = false
            return
        }

        if (selectedRuntime != RuntimeMode.AGENT) {
            suppressSlashPopupUntilReset = false
            lastSlashMatches = emptyList()
            hideSlashPopup()
            return
        }

        val value = inputArea.text.trim()
        if (value.isBlank() || !value.startsWith("/")) {
            suppressSlashPopupUntilReset = false
            lastSlashMatches = emptyList()
            hideSlashPopup()
            return
        }
        val token = value.removePrefix("/").lowercase()
        if (token.contains(" ")) {
            hideSlashPopup()
            return
        }
        if (suppressSlashPopupUntilReset) {
            hideSlashPopup()
            return
        }

        val matchedCommands = openCodeController.filterSuggestions(token)
        if (matchedCommands.isEmpty() && openCodeController.currentCatalog().isEmpty()) {
            refreshOpenCodeCatalogAsync()
        }
        val matches = matchedCommands.map { OpenCodeAgentCommandController.renderSuggestion(it) }
        if (matches.isEmpty()) {
            lastSlashMatches = emptyList()
            hideSlashPopup()
            return
        }
        if (matches == lastSlashMatches && slashPopup != null) {
            return
        }

        hideSlashPopup()
        val step = object : BaseListPopupStep<String>("OpenCode", matches) {
            override fun onChosen(selectedValue: String?, finalChoice: Boolean): PopupStep<*> {
                if (selectedValue != null) {
                    val selectedKey = selectedValue.removePrefix("/").substringBefore(" ").trim()
                    val command = matchedCommands.firstOrNull { it.name == selectedKey } ?: return FINAL_CHOICE
                    isApplyingSlashSelection = true
                    suppressSlashPopupUntilReset = true
                    inputArea.text = OpenCodeAgentCommandController.selectionText(command)
                    inputArea.caretPosition = inputArea.text.length
                    hideSlashPopup()
                }
                return FINAL_CHOICE
            }
        }
        val popup = JBPopupFactory.getInstance().createListPopup(step)
        popup.addListener(object : JBPopupListener {
            override fun onClosed(event: LightweightWindowEvent) {
                if (slashPopup == popup) slashPopup = null
            }
        })
        lastSlashMatches = matches
        slashPopup = popup
        popup.show(RelativePoint.getSouthWestOf(inputArea))
    }

    private fun hideSlashPopup() {
        slashPopup?.cancel()
        slashPopup = null
    }

    private fun refreshOpenCodeCatalogAsync() {
        if (selectedRuntime != RuntimeMode.AGENT) return
        val projectRoot = currentRuntimeProjectRoot(RuntimeMode.AGENT)
        if (projectRoot.isBlank()) return
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                openCodeController.refreshCatalog(projectRoot)
            } catch (ex: Exception) {
                logger.debug("Failed to refresh OpenCode command catalog", ex)
            }
        }
    }

    private fun handleOpenCodeExecutionResponse(response: OpenCodeCommandExecutionResponseDto) {
        removeProgressLine()
        updateSendButtonState()
        updateStatusLabel()
        response.sessionId?.takeIf { it.isNotBlank() }?.let { activeSession ->
            sessionId = activeSession
            sessionIdsByRuntime[selectedRuntime] = activeSession
            syncPlanModeCheckboxFromSession()
            initialSessionRequested = true
            initialSessionReady = true
            if (selectedRuntime == RuntimeMode.AGENT) {
                startEventStreamAsync(activeSession)
            }
        }
        when (response.kind.lowercase()) {
            "run" -> {
                latestActivity = "busy"
                refreshControlPlaneAsync()
            }
            "native_action" -> handleNativeOpenCodeAction(response.nativeAction)
            "catalog" -> showCommandCatalogPopup(response)
            "status" -> showOpenCodeStatusPopup(response)
            "resource" -> showOpenCodeResourcePopup(response)
            else -> {
                latestActivity = "idle"
                val message = response.message?.takeIf { it.isNotBlank() }
                    ?: response.result["message"]?.toString()?.takeIf { it.isNotBlank() }
                    ?: "/${response.commandId} выполнена"
                appendSystemLine(message)
            }
        }
    }

    private fun handleNativeOpenCodeAction(nativeAction: String?) {
        when (nativeAction) {
            "new_session" -> ensureSessionAsync(forceNew = true)
            "open_history" -> {
                showHistoryScreen()
                loadSessionsHistoryAsync()
            }
            "open_editor" -> {
                inputArea.requestFocusInWindow()
                appendSystemLine("Команда /editor обрабатывается в IDE.")
            }
            else -> appendSystemLine("Команда выполнена.")
        }
    }

    private fun showCommandCatalogPopup(response: OpenCodeCommandExecutionResponseDto) {
        val commands = (response.result["commands"] as? List<*>)?.mapNotNull { item ->
            item as? Map<*, *>
        }.orEmpty()
        if (commands.isEmpty()) {
            appendSystemLine("Список команд пуст.")
            return
        }
        val lines = commands.map { item ->
            val name = item["name"]?.toString()?.trim().orEmpty()
            val description = item["description"]?.toString()?.trim().orEmpty()
            if (description.isBlank()) "/$name" else "/$name - $description"
        }
        showTextPopup("OpenCode команды", lines.joinToString("\n"))
    }

    private fun showOpenCodeStatusPopup(response: OpenCodeCommandExecutionResponseDto) {
        val rawStatus = response.result["status"] as? Map<*, *> ?: run {
            appendSystemLine("Статус OpenCode недоступен.")
            return
        }
        val config = rawStatus["config"] as? Map<*, *> ?: emptyMap<String, Any?>()
        val commandCatalog = rawStatus["commandCatalog"] as? Map<*, *> ?: emptyMap<String, Any?>()
        val diffSummary = rawStatus["diffSummary"] as? Map<*, *> ?: emptyMap<String, Any?>()
        val providerId = rawStatus["providerId"]?.toString()?.trim().orEmpty()
        val modelId = rawStatus["modelId"]?.toString()?.trim().orEmpty()
        val resolvedModel = config["resolvedModel"]?.toString()?.trim().orEmpty()
        val effectiveModel = listOfNotNull(providerId.takeIf { it.isNotBlank() }, modelId.takeIf { it.isNotBlank() })
            .joinToString("/")
            .ifBlank { resolvedModel.ifBlank { "-" } }
        val lines = listOf(
            "Session: ${rawStatus["sessionId"] ?: "-"}",
            "Activity: ${rawStatus["activity"] ?: "-"}",
            "Action: ${rawStatus["currentAction"] ?: "-"}",
            "Backend session: ${rawStatus["backendSessionId"] ?: "-"}",
            "Agent: ${rawStatus["agentId"] ?: "-"}",
            "Model: $effectiveModel",
            "Config: ${config["activeConfigFile"] ?: "-"}",
            "MCPs: ${rawStatus["mcpCount"] ?: 0}",
            "Commands: ${commandCatalog["total"] ?: 0}",
            "Diff: files=${diffSummary["files"] ?: 0}, +${diffSummary["additions"] ?: 0}, -${diffSummary["deletions"] ?: 0}"
        )
        showTextPopup("OpenCode status", lines.joinToString("\n"))
    }

    private fun showOpenCodeResourcePopup(response: OpenCodeCommandExecutionResponseDto) {
        val resourceKind = response.result["resourceKind"]?.toString()?.ifBlank { "resource" } ?: "resource"
        val items = (response.result["items"] as? List<*>)?.mapNotNull { item ->
            item as? Map<*, *>
        }.orEmpty()
        if (items.isEmpty()) {
            appendSystemLine("Список $resourceKind пуст.")
            return
        }
        val labels = items.map { item ->
            val name = item["name"]?.toString()?.trim().orEmpty()
            val description = item["description"]?.toString()?.trim().orEmpty()
            if (description.isBlank()) name else "$name - $description"
        }
        val step = object : BaseListPopupStep<String>(resourceKind.replaceFirstChar(Char::uppercase), labels) {
            override fun onChosen(selectedValue: String?, finalChoice: Boolean): PopupStep<*> {
                val selectedIndex = labels.indexOf(selectedValue)
                val item = items.getOrNull(selectedIndex) ?: return FINAL_CHOICE
                val details = buildString {
                    item["name"]?.let { appendLine("Name: $it") }
                    item["path"]?.let { appendLine("Path: $it") }
                    item["providerId"]?.let { appendLine("Provider: $it") }
                    item["id"]?.let { appendLine("Id: $it") }
                    item["transport"]?.let { appendLine("Transport: $it") }
                    item["description"]?.let { appendLine("Description: $it") }
                }.trim()
                if (details.isNotBlank()) {
                    showTextPopup(resourceKind, details)
                }
                return FINAL_CHOICE
            }
        }
        val popup = JBPopupFactory.getInstance().createListPopup(step)
        popup.show(RelativePoint.getSouthWestOf(inputArea))
    }

    private fun showTextPopup(title: String, text: String) {
        val textArea = JBTextArea(text).apply {
            isEditable = false
            lineWrap = true
            wrapStyleWord = true
            rows = 12
            columns = 56
            border = JBUI.Borders.empty(8)
            background = theme.containerBackground
            foreground = theme.primaryText
            caretColor = theme.primaryText
        }
        JBPopupFactory.getInstance()
            .createComponentPopupBuilder(JBScrollPane(textArea), textArea)
            .setRequestFocus(true)
            .setResizable(true)
            .setMovable(true)
            .setTitle(title)
            .createPopup()
            .show(RelativePoint.getSouthWestOf(inputArea))
    }

    private fun actionButton(text: String, action: () -> Unit): JButton = JButton(text).apply {
        foreground = theme.primaryText
        background = theme.controlBackground
        border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
        isContentAreaFilled = true
        isFocusPainted = false
        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        addActionListener { action() }
    }

    private data class UiLine(
        val kind: UiLineKind,
        val text: String,
        val createdAt: Instant,
        val stableKey: String,
        val source: UiLineSource
    )

    private enum class RuntimeMode(
        val backendValue: String,
        val title: String,
        val defaultProfile: String
    ) {
        CHAT("chat", "Chat", "quick"),
        AGENT("opencode", "Agent", "agent")
    }

    private enum class UiLineSource {
        SERVER_MESSAGE,
        SERVER_EVENT,
        LOCAL_SYSTEM,
        PROGRESS
    }

    private enum class ConnectionState {
        CONNECTING,
        CONNECTED,
        RECONNECTING,
        OFFLINE
    }

    private enum class UiLineKind {
        USER,
        AGENT_EVENT,
        QUESTION,
        ASSISTANT,
        SYSTEM,
        PROGRESS
    }

    private fun runtimeModeFromBackend(value: String?): RuntimeMode =
        RuntimeMode.values().firstOrNull { it.backendValue.equals(value ?: "chat", ignoreCase = true) } ?: RuntimeMode.CHAT

    private fun uiThemeColor(keys: List<String>, fallback: Color): JBColor {
        val resolved = keys.asSequence().mapNotNull { UIManager.getColor(it) }.firstOrNull() ?: fallback
        return JBColor(resolved, resolved)
    }

    private fun renderTimeline() {
        val visibleLines = timelineLines.filterNot { !showAgentTrace && it.kind == UiLineKind.AGENT_EVENT }
        timelineContainer.removeAll()
        if (visibleLines.isEmpty()) {
            timelineContainer.add(
                JBLabel("\u0417\u0430\u0434\u0430\u0439\u0442\u0435 \u0432\u043e\u043f\u0440\u043e\u0441 \u043f\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0443").apply {
                    foreground = theme.secondaryText
                    border = JBUI.Borders.empty(12, 10, 8, 10)
                }
            )
        } else {
            visibleLines.forEach { line -> timelineContainer.add(buildTimelineLine(line)) }
        }
        timelineContainer.revalidate()
        timelineContainer.repaint()
    }

    private fun updateTraceToggleState() {
        val isAgent = selectedRuntime == RuntimeMode.AGENT
        traceToggleButton.isVisible = isAgent
        traceToggleButton.text = if (showAgentTrace) "\u0421\u043a\u0440\u044b\u0442\u044c \u0442\u0440\u0430\u0441\u0441\u0443" else "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0442\u0440\u0430\u0441\u0441\u0443"
    }

    private fun buildTimelineLine(line: UiLine): JPanel {
        val viewportWidth = timelineScrollPane?.viewport?.extentSize?.width ?: width
        val contentWidth = maxOf(140, viewportWidth - 56)
        val textArea = JBTextArea(line.text).apply {
            isEditable = false
            isFocusable = true
            isOpaque = false
            lineWrap = true
            wrapStyleWord = true
            font = font.deriveFont(13.5f)
            foreground = if (line.kind == UiLineKind.SYSTEM) theme.systemText else theme.primaryText
            border = JBUI.Borders.empty(8, 11)
            setSize(Dimension(contentWidth, Int.MAX_VALUE))
            preferredSize = Dimension(contentWidth, preferredSize.height)
            maximumSize = Dimension(contentWidth, Int.MAX_VALUE)
        }

        val row = JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.empty(4, 8, 4, 8)
        }

        when (line.kind) {
            UiLineKind.USER -> {
                val bubble = JPanel(BorderLayout()).apply {
                    isOpaque = true
                    background = theme.userBubble
                    border = JBUI.Borders.compound(
                        RoundedLineBorder(theme.userBubbleBorder, 1, 18),
                        JBUI.Borders.empty()
                    )
                    add(textArea, BorderLayout.CENTER)
                    maximumSize = Dimension(contentWidth, Int.MAX_VALUE)
                }
                row.add(bubble, BorderLayout.CENTER)
            }
            UiLineKind.ASSISTANT -> {
                row.add(textArea, BorderLayout.CENTER)
            }
            UiLineKind.QUESTION -> {
                val bubble = JPanel(BorderLayout()).apply {
                    isOpaque = true
                    background = theme.containerBackground
                    border = JBUI.Borders.compound(
                        RoundedLineBorder(theme.controlBorder, 1, 14),
                        JBUI.Borders.empty()
                    )
                    add(textArea, BorderLayout.CENTER)
                    maximumSize = Dimension(contentWidth, Int.MAX_VALUE)
                }
                row.add(bubble, BorderLayout.WEST)
            }
            UiLineKind.AGENT_EVENT -> {
                val bubble = JPanel(BorderLayout()).apply {
                    isOpaque = true
                    background = theme.progressBubble
                    border = JBUI.Borders.compound(
                        RoundedLineBorder(theme.containerBorder, 1, 14),
                        JBUI.Borders.empty()
                    )
                    add(textArea, BorderLayout.CENTER)
                    maximumSize = Dimension(contentWidth, Int.MAX_VALUE)
                }
                row.add(bubble, BorderLayout.WEST)
            }
            UiLineKind.PROGRESS -> {
                val bubble = JPanel(BorderLayout()).apply {
                    isOpaque = true
                    background = theme.progressBubble
                    border = JBUI.Borders.compound(
                        RoundedLineBorder(theme.containerBorder, 1, 14),
                        JBUI.Borders.empty()
                    )
                    add(textArea, BorderLayout.CENTER)
                    maximumSize = Dimension(contentWidth, Int.MAX_VALUE)
                }
                row.add(bubble, BorderLayout.WEST)
            }
            UiLineKind.SYSTEM -> {
                row.add(textArea, BorderLayout.WEST)
            }
        }
        return row
    }

    private inner class UiTheme {
        val panelBackground: JBColor = uiThemeColor(listOf("Panel.background"), Color(0x2E, 0x32, 0x39))
        val containerBackground: JBColor = uiThemeColor(listOf("TextArea.background", "Panel.background"), Color(0x35, 0x39, 0x41))
        val inputBackground: JBColor = uiThemeColor(listOf("TextField.background", "TextArea.background"), Color(0x3A, 0x3F, 0x47))
        val controlBackground: JBColor = uiThemeColor(listOf("Button.background", "Panel.background"), Color(0x3C, 0x41, 0x49))
        val containerBorder: JBColor = uiThemeColor(listOf("Component.borderColor", "Borders.color"), Color(0x4A, 0x50, 0x5A))
        val controlBorder: JBColor = uiThemeColor(listOf("Component.borderColor", "Borders.color"), Color(0x52, 0x59, 0x64))
        val primaryText: JBColor = uiThemeColor(listOf("Label.foreground"), Color(0xE7, 0xEA, 0xEF))
        val secondaryText: JBColor = uiThemeColor(listOf("Label.disabledForeground", "Component.infoForeground"), Color(0x9A, 0xA1, 0xAD))
        val systemText: JBColor = uiThemeColor(listOf("Component.errorFocusColor", "ValidationTooltip.errorForeground"), Color(0xD8, 0x5D, 0x5D))
        val sendButtonBackground: JBColor = uiThemeColor(listOf("Button.default.background"), Color(0x66, 0x7A, 0x9B))
        val stopButtonBackground: JBColor = uiThemeColor(listOf("Actions.Red"), Color(0xC2, 0x4A, 0x4A))
        val userBubble: JBColor = uiThemeColor(listOf("EditorPane.background", "TextArea.background"), Color(0x56, 0x5D, 0x69))
        val userBubbleBorder: JBColor = uiThemeColor(listOf("Component.borderColor", "Borders.color"), Color(0x63, 0x6B, 0x77))
        val progressBubble: JBColor = uiThemeColor(listOf("ToolTip.background", "Panel.background"), Color(0x4E, 0x55, 0x61))
    }

    private class RoundedLineBorder(
        private val color: Color,
        private val strokeWidth: Int,
        private val arc: Int
    ) : AbstractBorder() {
        override fun getBorderInsets(c: Component?): Insets = Insets(1, 1, 1, 1)

        override fun paintBorder(c: Component?, g: Graphics, x: Int, y: Int, width: Int, height: Int) {
            val g2 = g.create() as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            g2.color = color
            g2.stroke = java.awt.BasicStroke(strokeWidth.toFloat())
            g2.drawRoundRect(x, y, width - strokeWidth, height - strokeWidth, arc, arc)
            g2.dispose()
        }
    }

    private inner class SessionRenderer(private val formatter: DateTimeFormatter) : DefaultListCellRenderer() {
        override fun getListCellRendererComponent(
            list: JList<*>,
            value: Any?,
            index: Int,
            isSelected: Boolean,
            cellHasFocus: Boolean
        ): Component {
            val item = value as? ChatSessionListItemDto
            val text = if (item == null) {
                ""
            } else {
                val preview = item.lastMessagePreview?.takeIf { it.isNotBlank() } ?: "\u0421\u0435\u0441\u0441\u0438\u044f ${item.sessionId.take(8)}"
                "[${runtimeModeFromBackend(item.runtime).title}] $preview  |  ${formatter.format(item.updatedAt)}  |  ${item.activity}"
            }
            return (super.getListCellRendererComponent(list, text, index, isSelected, cellHasFocus) as DefaultListCellRenderer).apply {
                border = JBUI.Borders.empty(8, 10)
                foreground = if (isSelected) theme.primaryText else theme.primaryText
                background = if (isSelected) theme.controlBackground else theme.containerBackground
            }
        }
    }

    private inner class RuntimeModeRenderer : DefaultListCellRenderer() {
        override fun getListCellRendererComponent(
            list: JList<*>,
            value: Any?,
            index: Int,
            isSelected: Boolean,
            cellHasFocus: Boolean
        ): Component {
            val mode = value as? RuntimeMode
            return (super.getListCellRendererComponent(list, mode?.title ?: "", index, isSelected, cellHasFocus) as DefaultListCellRenderer).apply {
                foreground = theme.primaryText
                background = if (isSelected) theme.controlBackground else theme.containerBackground
                border = JBUI.Borders.empty(4, 8)
            }
        }
    }
}

internal data class AgentQuestionCard(
    val title: String,
    val choices: List<String>,
    val allowCustomAnswer: Boolean,
    val kind: String = "clarification"
)

internal fun shouldProcessRuntimeSelectionChange(
    suppressListener: Boolean,
    target: Any?,
    selectedRuntime: Any?
): Boolean {
    if (suppressListener) return false
    return target != null && target != selectedRuntime
}

internal fun shouldApplyUiRefresh(
    requestedSessionId: String?,
    historySessionId: String?,
    statusSessionId: String?,
    activeSessionId: String?
): Boolean {
    val active = activeSessionId?.trim().orEmpty()
    val requested = requestedSessionId?.trim().orEmpty()
    val history = historySessionId?.trim().orEmpty()
    val status = statusSessionId?.trim().orEmpty()
    if (active.isBlank() || requested.isBlank() || history.isBlank() || status.isBlank()) return false
    return requested == active && history == active && status == active
}

internal fun buildStatusDetails(connectionDetails: String?, planModeEnabled: Boolean): String? {
    val chunks = mutableListOf<String>()
    if (planModeEnabled) {
        chunks += "Планирование"
    }
    connectionDetails?.takeIf { it.isNotBlank() }?.let { chunks += it }
    return chunks.takeIf { it.isNotEmpty() }?.joinToString(" | ")
}

internal fun extractQuestionChoices(metadata: Map<String, Any?>): List<String> {
    val rawChoices = metadata["choices"] as? List<*> ?: return emptyList()
    return rawChoices
        .mapNotNull { item ->
            when (item) {
                is String -> item.trim()
                is Map<*, *> -> item["label"]?.toString()?.trim()
                else -> item?.toString()?.trim()
            }?.takeIf { it.isNotBlank() }
        }
        .distinctBy { it.lowercase() }
}

internal fun extractQuestionKind(metadata: Map<String, Any?>): String =
    metadata["questionKind"]?.toString()?.trim()?.takeIf { it.isNotBlank() } ?: "clarification"

internal fun extractLatestPendingQuestion(messages: List<ru.sber.aitestplugin.model.ChatMessageDto>): AgentQuestionCard? {
    val indexedQuestion = messages.withIndex().lastOrNull { (_, message) ->
        message.role.equals("assistant", ignoreCase = true) && message.metadata["question"] == true
    } ?: return null
    val hasUserReplyAfter = messages.drop(indexedQuestion.index + 1).any { message ->
        message.role.equals("user", ignoreCase = true)
    }
    if (hasUserReplyAfter) {
        return null
    }
    val kind = extractQuestionKind(indexedQuestion.value.metadata)
    val choices = if (kind == "plan_confirmation") {
        listOf("Продолжить", "Уточнить план")
    } else {
        extractQuestionChoices(indexedQuestion.value.metadata)
    }
    return AgentQuestionCard(
        title = if (kind == "plan_confirmation") "Подтвердите план" else indexedQuestion.value.content,
        choices = choices,
        allowCustomAnswer = indexedQuestion.value.metadata["allowCustomAnswer"] != false,
        kind = kind
    )
}

internal fun resolveRuntimeProjectRootValue(runtime: String, projectBasePath: String?): String {
    return when (runtime.trim().lowercase()) {
        "opencode" -> projectBasePath.orEmpty()
        else -> projectBasePath.orEmpty()
    }
}

internal fun resolveContextPercent(percent: Double?, used: Int, contextWindow: Int?): Int {
    val direct = percent?.times(100.0)?.toInt()
    if (direct != null) {
        return direct.coerceIn(0, 100)
    }
    val window = contextWindow ?: return 0
    if (window <= 0) return 0
    return ((used.toDouble() / window.toDouble()) * 100.0).toInt().coerceIn(0, 100)
}

internal fun opencodeCliTokenTotal(input: Int, output: Int, reasoning: Int): Int =
    (input + output + reasoning).coerceAtLeast(0)

internal fun buildStatusLabelText(
    runtimeText: String,
    activityText: String,
    connectionText: String,
    details: String?,
    contextPercent: Int?,
    tokenTotal: Int?
): String {
    val chunks = mutableListOf(runtimeText, activityText, connectionText)
    contextPercent?.let { chunks += "Контекст ${it}%" }
    tokenTotal?.let { chunks += "Токены $it" }
    details?.takeIf { it.isNotBlank() }?.let { chunks += it }
    return chunks.joinToString(" | ")
}







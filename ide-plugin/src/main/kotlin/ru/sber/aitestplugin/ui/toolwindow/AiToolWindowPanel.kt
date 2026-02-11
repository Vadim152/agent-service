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
import ru.sber.aitestplugin.model.ChatCommandRequestDto
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatPendingPermissionDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatSessionListItemDto
import ru.sber.aitestplugin.model.ChatSessionStatusResponseDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.CardLayout
import java.awt.Color
import java.awt.Component
import java.awt.Cursor
import java.awt.Dimension
import java.awt.FlowLayout
import java.awt.Font
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
import javax.swing.JList
import javax.swing.JPanel
import javax.swing.SwingUtilities
import javax.swing.Timer
import javax.swing.UIManager
import javax.swing.event.DocumentEvent
import javax.swing.event.DocumentListener

class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient()
) : JPanel(BorderLayout()) {
    private val logger = Logger.getInstance(AiToolWindowPanel::class.java)
    private val settings = AiTestPluginSettingsService.getInstance().settings
    private val refreshInFlight = AtomicBoolean(false)
    private val streamClient = OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val pollTimer = Timer(3000) { refreshControlPlaneAsync() }
    private val uiRefreshDebounceMs = 200
    private val autoScrollBottomThresholdPx = 48
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault())
    private val supportedCommands = listOf("status", "diff", "compact", "abort", "help")
    private val sseIndexPattern = Regex("\"index\"\\s*:\\s*(\\d+)")
    private val theme = UiTheme()

    private val cardLayout = CardLayout()
    private val bodyCards = JPanel(cardLayout)
    private val timelineModel = DefaultListModel<UiLine>()
    private val timeline = JBList(timelineModel)
    private val historyModel = DefaultListModel<ChatSessionListItemDto>()
    private val historyList = JBList(historyModel)

    private val inputArea = JBTextArea(4, 20)
    private val sendButton = JButton()
    private val statusLabel = JBLabel("Connecting...")

    private val approvalPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        isOpaque = false
        border = JBUI.Borders.empty(6, 8, 4, 8)
    }
    private val uiApplyTimer = Timer(uiRefreshDebounceMs) { applyPendingUiRefresh() }.apply { isRepeats = false }

    private var sessionId: String? = null
    private var streamSessionId: String? = null
    private var streamCall: Call? = null
    private var slashPopup: JBPopup? = null
    private var isApplyingSlashSelection: Boolean = false
    private var suppressSlashPopupUntilReset: Boolean = false
    private var lastSlashMatches: List<String> = emptyList()
    private var latestActivity: String = "idle"
    private var connectionState: ConnectionState = ConnectionState.CONNECTING
    private var connectionDetails: String? = null
    private var streamReconnectAttempt: Int = 0
    private var streamFromIndex: Int = 0
    private var timelineScrollPane: JBScrollPane? = null
    private var pendingHistoryForRender: ChatHistoryResponseDto? = null
    private var pendingStatusForRender: ChatSessionStatusResponseDto? = null

    init {
        border = JBUI.Borders.empty(8, 8, 10, 8)
        background = theme.panelBackground
        isOpaque = true
        add(buildRoot(), BorderLayout.CENTER)
        updateStatusLabel()
        ensureSessionAsync(forceNew = true)
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
        appendSystemLine("Scan completed: steps=${response.stepsCount}, updated=${response.updatedAt}.")
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        if (unmappedSteps.isNotEmpty()) {
            appendSystemLine("Unmapped steps: ${unmappedSteps.size}")
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

    private fun buildHeader(): JPanel {
        return JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.empty(0, 2, 8, 2)
            add(JBLabel(ToolWindowIds.DISPLAY_NAME).apply {
                font = font.deriveFont(Font.BOLD, 16f)
                foreground = theme.primaryText
            }, BorderLayout.WEST)
            add(
                JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                    isOpaque = false
                    add(headerButton("+") { ensureSessionAsync(forceNew = true) })
                    add(headerButton("History") {
                        showHistoryScreen()
                        loadSessionsHistoryAsync()
                    })
                    add(JButton(AllIcons.General.Settings).apply {
                        toolTipText = "Settings"
                        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
                        foreground = theme.primaryText
                        background = theme.controlBackground
                        border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
                        isContentAreaFilled = true
                        isFocusPainted = false
                        addActionListener {
                            ShowSettingsUtil.getInstance().showSettingsDialog(
                                project,
                                AiTestPluginSettingsConfigurable::class.java
                            )
                        }
                    })
                },
                BorderLayout.EAST
            )
        }
    }

    private fun buildBody(): JPanel {
        bodyCards.isOpaque = false
        bodyCards.add(buildChatCard(), "chat")
        bodyCards.add(buildHistoryCard(), "history")
        cardLayout.show(bodyCards, "chat")
        return bodyCards
    }

    private fun buildChatCard(): JPanel {
        timeline.cellRenderer = BubbleRenderer()
        timeline.fixedCellHeight = -1
        timeline.background = theme.panelBackground
        timeline.foreground = theme.primaryText
        timeline.selectionBackground = theme.panelBackground
        timeline.selectionForeground = theme.primaryText
        timeline.emptyText.text = "Ask anything about your project"

        return JPanel(BorderLayout()).apply {
            isOpaque = false
            add(JBScrollPane(timeline).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty(2)
                )
                background = theme.panelBackground
                viewport.background = theme.panelBackground
                preferredSize = Dimension(100, 360)
                timelineScrollPane = this
            }, BorderLayout.CENTER)
            add(approvalPanel, BorderLayout.SOUTH)
        }
    }

    private fun buildHistoryCard(): JPanel {
        historyList.cellRenderer = SessionRenderer(timeFormatter)
        historyList.background = theme.containerBackground
        historyList.foreground = theme.primaryText
        historyList.selectionBackground = theme.controlBackground
        historyList.selectionForeground = theme.primaryText
        historyList.emptyText.text = "No chats yet"
        historyList.addMouseListener(object : java.awt.event.MouseAdapter() {
            override fun mouseClicked(e: java.awt.event.MouseEvent) {
                if (e.clickCount >= 2) {
                    historyList.selectedValue?.let { activateSession(it.sessionId) }
                }
            }
        })

        val root = JPanel(BorderLayout()).apply {
            isOpaque = false
            add(
                JPanel(BorderLayout()).apply {
                    isOpaque = false
                    add(JButton("Back").apply {
                        foreground = theme.primaryText
                        background = theme.controlBackground
                        border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
                        isContentAreaFilled = true
                        isFocusPainted = false
                        addActionListener { showChatScreen() }
                    }, BorderLayout.WEST)
                    add(JBLabel("History").apply { foreground = theme.primaryText }, BorderLayout.CENTER)
                },
                BorderLayout.NORTH
            )
            add(JBScrollPane(historyList).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty(2)
                )
                viewport.background = theme.containerBackground
            }, BorderLayout.CENTER)
            add(JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
                isOpaque = false
                add(JButton("Open Chat").apply {
                    foreground = theme.primaryText
                    background = theme.controlBackground
                    border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
                    isContentAreaFilled = true
                    isFocusPainted = false
                    addActionListener { historyList.selectedValue?.let { activateSession(it.sessionId) } }
                })
            }, BorderLayout.SOUTH)
        }
        return root
    }

    private fun buildInput(): JPanel {
        inputArea.lineWrap = true
        inputArea.wrapStyleWord = true
        inputArea.background = theme.inputBackground
        inputArea.foreground = theme.primaryText
        inputArea.caretColor = theme.primaryText
        inputArea.border = JBUI.Borders.empty(4, 6)
        inputArea.font = inputArea.font.deriveFont(14f)
        inputArea.putClientProperty("JTextArea.placeholderText", "Type / for commands, # for prompts or @ to add context")
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
        sendButton.border = BorderFactory.createEmptyBorder(0, 0, 0, 0)
        sendButton.isBorderPainted = false
        sendButton.isFocusPainted = false
        sendButton.isContentAreaFilled = true
        sendButton.addActionListener { onSendOrStop() }
        updateSendButtonState()

        return JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.emptyTop(8)
            add(
                JPanel(BorderLayout()).apply {
                    isOpaque = true
                    background = theme.inputBackground
                    border = JBUI.Borders.compound(
                        BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                        JBUI.Borders.empty(8, 8, 8, 6)
                    )
                    add(JBScrollPane(inputArea).apply {
                        border = JBUI.Borders.empty()
                        background = theme.inputBackground
                        viewport.background = theme.inputBackground
                    }, BorderLayout.CENTER)
                    add(JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
                        isOpaque = false
                        add(sendButton)
                    }, BorderLayout.EAST)
                },
                BorderLayout.CENTER
            )
            add(statusLabel.apply {
                foreground = theme.secondaryText
                border = JBUI.Borders.empty(6, 6, 0, 6)
            }, BorderLayout.SOUTH)
        }
    }

    private fun headerButton(text: String, action: () -> Unit): JButton = JButton(text).apply {
        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
        foreground = theme.primaryText
        background = theme.controlBackground
        border = BorderFactory.createLineBorder(theme.controlBorder, 1, true)
        isContentAreaFilled = true
        isFocusPainted = false
        putClientProperty("JButton.buttonType", "roundRect")
        addActionListener { action() }
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
        if (input.startsWith("/")) {
            val command = input.removePrefix("/").substringBefore(" ").lowercase()
            if (command in supportedCommands) {
                inputArea.text = ""
                suppressSlashPopupUntilReset = false
                hideSlashPopup()
                submitCommand(command)
                return
            }
            appendSystemLine("Unknown command: /$command")
            return
        }
        submitMessage(input)
    }

    private fun submitMessage(message: String) {
        if (isGenerating()) {
            appendSystemLine("Wait until current response is finished.")
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            val active = ensureSessionBlocking(forceNew = false) ?: return@executeOnPooledThread
            try {
                backendClient.sendChatMessage(active, ChatMessageRequestDto(content = message))
                SwingUtilities.invokeLater {
                    inputArea.text = ""
                    suppressSlashPopupUntilReset = false
                    hideSlashPopup()
                    setConnectionState(ConnectionState.CONNECTED)
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to send chat message", ex)
                SwingUtilities.invokeLater { appendSystemLine("Message failed: ${ex.message}") }
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
                SwingUtilities.invokeLater { appendSystemLine("Command failed: ${ex.message}") }
            }
        }
    }

    private fun ensureSessionAsync(forceNew: Boolean) {
        ApplicationManager.getApplication().executeOnPooledThread {
            val active = ensureSessionBlocking(forceNew) ?: return@executeOnPooledThread
            SwingUtilities.invokeLater {
                showChatScreen()
                setConnectionState(ConnectionState.CONNECTING, "Session ${active.take(8)}")
            }
            startEventStreamAsync(active)
            refreshControlPlaneAsync()
        }
    }

    private fun ensureSessionBlocking(forceNew: Boolean): String? {
        if (!forceNew && !sessionId.isNullOrBlank()) return sessionId

        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath.orEmpty()
        if (projectRoot.isBlank()) {
            SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "Project root is empty") }
            return null
        }

        return try {
            val created = backendClient.createChatSession(
                ChatSessionCreateRequestDto(
                    projectRoot = projectRoot,
                    source = "ide-plugin",
                    profile = "quick",
                    reuseExisting = !forceNew
                )
            )
            sessionId = created.sessionId
            latestActivity = "idle"
            streamReconnectAttempt = 0
            streamFromIndex = 0
            if (forceNew || !created.reused) {
                SwingUtilities.invokeLater {
                    uiApplyTimer.stop()
                    pendingHistoryForRender = null
                    pendingStatusForRender = null
                    timelineModel.clear()
                    renderPendingApprovals(emptyList())
                }
            }
            created.sessionId
        } catch (ex: Exception) {
            logger.warn("Failed to create session", ex)
            SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "Init failed: ${ex.message}") }
            null
        }
    }

    private fun activateSession(targetSessionId: String) {
        sessionId = targetSessionId
        latestActivity = "idle"
        uiApplyTimer.stop()
        pendingHistoryForRender = null
        pendingStatusForRender = null
        timelineModel.clear()
        renderPendingApprovals(emptyList())
        streamReconnectAttempt = 0
        streamFromIndex = 0
        showChatScreen()
        startEventStreamAsync(targetSessionId)
        refreshControlPlaneAsync()
    }

    private fun loadSessionsHistoryAsync() {
        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath.orEmpty()
        if (projectRoot.isBlank()) {
            setConnectionState(ConnectionState.OFFLINE, "Project root is empty")
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
                SwingUtilities.invokeLater { setConnectionState(ConnectionState.OFFLINE, "History load failed") }
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
                    enqueueUiRefresh(history, status)
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) logger.debug("Refresh failed", ex)
            } finally {
                refreshInFlight.set(false)
            }
        }
    }

    private fun enqueueUiRefresh(history: ChatHistoryResponseDto, status: ChatSessionStatusResponseDto) {
        pendingHistoryForRender = history
        pendingStatusForRender = status
        uiApplyTimer.restart()
    }

    private fun applyPendingUiRefresh() {
        val history = pendingHistoryForRender ?: return
        val status = pendingStatusForRender ?: return
        pendingHistoryForRender = null
        pendingStatusForRender = null
        renderHistory(history)
        renderStatus(status)
    }

    private fun renderHistory(history: ChatHistoryResponseDto) {
        val shouldStickToBottom = isUserNearBottom()
        val serverLines = history.messages
            .filterNot { it.role.equals("assistant", ignoreCase = true) && it.content.trim().isBlank() }
            .sortedBy { it.createdAt }
            .map { message ->
                val lineKind = when (message.role.lowercase()) {
                    "user" -> UiLineKind.USER
                    "assistant" -> UiLineKind.ASSISTANT
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

        val localLines = (0 until timelineModel.size)
            .map { timelineModel.get(it) }
            .filter { it.source == UiLineSource.LOCAL_SYSTEM }
        val progressLine = (0 until timelineModel.size)
            .map { timelineModel.get(it) }
            .firstOrNull { it.source == UiLineSource.PROGRESS }

        val targetLines = buildList {
            addAll(serverLines)
            addAll(localLines)
            progressLine?.let { add(it) }
        }
        replaceTimelineModelIncrementally(targetLines)
        renderPendingApprovals(history.pendingPermissions)
        scrollToBottomIfNeeded(shouldStickToBottom)
    }

    private fun renderStatus(status: ChatSessionStatusResponseDto) {
        latestActivity = status.activity.lowercase()
        updateSendButtonState()

        val progress = when (latestActivity) {
            "busy" -> "Working: ${status.currentAction}"
            "retry" -> {
                val retry = status.lastRetryAttempt?.let { "Retry #$it" } ?: "Retry"
                "$retry: ${status.lastRetryMessage ?: status.currentAction}"
            }
            "waiting_permission" -> "Waiting approval: ${status.currentAction}"
            else -> null
        }
        if (progress != null) {
            upsertProgressLine(progress)
        } else {
            removeProgressLine()
        }
        updateStatusLabel()
    }

    private fun renderPendingApprovals(pending: List<ChatPendingPermissionDto>) {
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
            row.add(JBLabel("Approval: ${permission.title} (${permission.kind})").apply {
                foreground = theme.primaryText
            }, BorderLayout.CENTER)
            row.add(JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                isOpaque = false
                add(actionButton("Approve once") { submitApproval(permission, "approve_once") })
                add(actionButton("Approve always") { submitApproval(permission, "approve_always") })
                add(actionButton("Reject") { submitApproval(permission, "reject") })
            }, BorderLayout.EAST)
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
                SwingUtilities.invokeLater { appendSystemLine("Decision failed: ${ex.message}") }
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
            val request = Request.Builder().url("$base/chat/sessions/$activeSession/stream?fromIndex=$streamFromIndex").get().build()
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
                        setConnectionState(ConnectionState.RECONNECTING, "Empty response body")
                        scheduleStreamReconnect(activeSession, "empty-body")
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
                setConnectionState(ConnectionState.RECONNECTING, ex.message ?: "Stream disconnected")
                scheduleStreamReconnect(activeSession, ex.message ?: "disconnected")
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
        setConnectionState(ConnectionState.RECONNECTING, "Reconnecting in ${delayMs}ms ($reason)")
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
        sendButton.toolTipText = if (isGenerating()) "Stop generation" else "Send message"
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
        val activityText = when (latestActivity) {
            "busy" -> "Working"
            "retry" -> "Retrying"
            "waiting_permission" -> "Waiting for approval"
            "error" -> "Error"
            else -> "Ready"
        }
        val connectionText = when (connectionState) {
            ConnectionState.CONNECTING -> "connecting"
            ConnectionState.CONNECTED -> "connected"
            ConnectionState.RECONNECTING -> "reconnecting"
            ConnectionState.OFFLINE -> "offline"
        }
        val details = connectionDetails?.takeIf { it.isNotBlank() }
        val text = if (details != null) {
            "$activityText | $connectionText | $details"
        } else {
            "$activityText | $connectionText"
        }
        if (SwingUtilities.isEventDispatchThread()) {
            statusLabel.text = text
        } else {
            SwingUtilities.invokeLater { statusLabel.text = text }
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
        timelineModel.addElement(
            UiLine(
                kind = UiLineKind.SYSTEM,
                text = text,
                createdAt = Instant.now(),
                stableKey = "local-system-${System.nanoTime()}",
                source = UiLineSource.LOCAL_SYSTEM
            )
        )
        scrollToBottomIfNeeded(shouldStickToBottom)
    }

    private fun upsertProgressLine(text: String) {
        val shouldStickToBottom = isUserNearBottom()
        val idx = (0 until timelineModel.size).firstOrNull { timelineModel.get(it).source == UiLineSource.PROGRESS }
        if (idx == null) {
            timelineModel.addElement(
                UiLine(
                    kind = UiLineKind.PROGRESS,
                    text = text,
                    createdAt = Instant.now(),
                    stableKey = "progress",
                    source = UiLineSource.PROGRESS
                )
            )
        } else {
            val existing = timelineModel.get(idx)
            if (existing.text != text) {
                timelineModel.set(
                    idx,
                    existing.copy(text = text, createdAt = Instant.now())
                )
            }
        }
        scrollToBottomIfNeeded(shouldStickToBottom)
    }

    private fun removeProgressLine() {
        val idx = (0 until timelineModel.size).firstOrNull { timelineModel.get(it).source == UiLineSource.PROGRESS } ?: return
        timelineModel.remove(idx)
    }

    private fun replaceTimelineModelIncrementally(target: List<UiLine>) {
        val commonSize = minOf(timelineModel.size, target.size)
        for (index in 0 until commonSize) {
            val current = timelineModel.get(index)
            val next = target[index]
            if (current != next) {
                timelineModel.set(index, next)
            }
        }
        if (timelineModel.size > target.size) {
            for (index in timelineModel.size - 1 downTo target.size) {
                timelineModel.remove(index)
            }
        } else if (target.size > timelineModel.size) {
            for (index in timelineModel.size until target.size) {
                timelineModel.addElement(target[index])
            }
        }
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
        if (token in supportedCommands) {
            suppressSlashPopupUntilReset = true
            lastSlashMatches = emptyList()
            hideSlashPopup()
            return
        }
        if (suppressSlashPopupUntilReset) {
            hideSlashPopup()
            return
        }

        val matches = supportedCommands.filter { it.startsWith(token) }.map { "/$it" }
        if (matches.isEmpty()) {
            lastSlashMatches = emptyList()
            hideSlashPopup()
            return
        }
        if (matches == lastSlashMatches && slashPopup != null) {
            return
        }

        hideSlashPopup()
        val step = object : BaseListPopupStep<String>("Commands", matches) {
            override fun onChosen(selectedValue: String?, finalChoice: Boolean): PopupStep<*> {
                if (selectedValue != null) {
                    isApplyingSlashSelection = true
                    suppressSlashPopupUntilReset = true
                    inputArea.text = selectedValue
                    inputArea.caretPosition = inputArea.text.length
                    hideSlashPopup()
                    submitInput(selectedValue)
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

    private enum class UiLineSource {
        SERVER_MESSAGE,
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
        ASSISTANT,
        SYSTEM,
        PROGRESS
    }

    private fun uiThemeColor(keys: List<String>, fallback: Color): JBColor {
        val resolved = keys.asSequence().mapNotNull { UIManager.getColor(it) }.firstOrNull() ?: fallback
        return JBColor(resolved, resolved)
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
        val userBubble: JBColor = uiThemeColor(listOf("EditorPane.background", "TextArea.background"), Color(0x47, 0x4D, 0x58))
        val assistantBubble: JBColor = uiThemeColor(listOf("TextArea.background", "Panel.background"), Color(0x3E, 0x44, 0x4E))
        val progressBubble: JBColor = uiThemeColor(listOf("ToolTip.background", "Panel.background"), Color(0x4E, 0x55, 0x61))
    }

    private inner class BubbleRenderer : DefaultListCellRenderer() {
        override fun getListCellRendererComponent(
            list: JList<*>,
            value: Any?,
            index: Int,
            isSelected: Boolean,
            cellHasFocus: Boolean
        ): Component {
            val line = value as? UiLine ?: return super.getListCellRendererComponent(list, "", index, false, false)
            val textArea = JBTextArea(line.text).apply {
                isEditable = false
                isFocusable = false
                isOpaque = false
                lineWrap = true
                wrapStyleWord = true
                border = JBUI.Borders.empty(8, 11)
                font = list.font.deriveFont(13.5f)
            }

            if (line.kind == UiLineKind.SYSTEM) {
                textArea.foreground = theme.systemText
                return JPanel(BorderLayout()).apply {
                    isOpaque = false
                    border = JBUI.Borders.empty(2, 10, 2, 10)
                    add(textArea, BorderLayout.WEST)
                }
            }

            textArea.foreground = theme.primaryText
            val bubbleBackground = when (line.kind) {
                UiLineKind.USER -> theme.userBubble
                UiLineKind.ASSISTANT -> theme.assistantBubble
                UiLineKind.PROGRESS -> theme.progressBubble
                UiLineKind.SYSTEM -> theme.panelBackground
            }

            val bubble = JPanel(BorderLayout()).apply {
                isOpaque = true
                background = bubbleBackground
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(theme.containerBorder, 1, true),
                    JBUI.Borders.empty()
                )
                add(textArea, BorderLayout.CENTER)
            }

            return JPanel(BorderLayout()).apply {
                isOpaque = false
                border = JBUI.Borders.empty(5, 8, 5, 8)
                if (line.kind == UiLineKind.USER) add(bubble, BorderLayout.EAST) else add(bubble, BorderLayout.WEST)
            }
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
                val preview = item.lastMessagePreview?.takeIf { it.isNotBlank() } ?: "Session ${item.sessionId.take(8)}"
                "$preview  |  ${formatter.format(item.updatedAt)}  |  ${item.activity}"
            }
            return (super.getListCellRendererComponent(list, text, index, isSelected, cellHasFocus) as DefaultListCellRenderer).apply {
                border = JBUI.Borders.empty(8, 10)
                foreground = if (isSelected) theme.primaryText else theme.primaryText
                background = if (isSelected) theme.controlBackground else theme.containerBackground
            }
        }
    }
}



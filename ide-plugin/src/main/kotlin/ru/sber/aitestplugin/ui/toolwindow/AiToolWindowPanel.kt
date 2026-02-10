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
    private val pollTimer = Timer(1800) { refreshControlPlaneAsync() }
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault())
    private val supportedCommands = listOf("status", "diff", "compact", "abort", "help")

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

    private var sessionId: String? = null
    private var streamSessionId: String? = null
    private var streamCall: Call? = null
    private var slashPopup: JBPopup? = null
    private var latestActivity: String = "idle"

    init {
        border = JBUI.Borders.empty(8)
        background = JBColor.PanelBackground
        add(buildRoot(), BorderLayout.CENTER)
        ensureSessionAsync(forceNew = true)
    }

    override fun addNotify() {
        super.addNotify()
        pollTimer.start()
        sessionId?.let { startEventStreamAsync(it) }
    }

    override fun removeNotify() {
        pollTimer.stop()
        stopEventStream()
        slashPopup?.cancel()
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
            isOpaque = false
            add(buildHeader(), BorderLayout.NORTH)
            add(buildBody(), BorderLayout.CENTER)
            add(buildInput(), BorderLayout.SOUTH)
        }
    }

    private fun buildHeader(): JPanel {
        return JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.emptyBottom(8)
            add(JBLabel(ToolWindowIds.DISPLAY_NAME).apply {
                font = font.deriveFont(15f)
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
        timeline.emptyText.text = "Ask anything about your project"

        return JPanel(BorderLayout()).apply {
            isOpaque = false
            add(JBScrollPane(timeline).apply {
                border = JBUI.Borders.customLine(JBColor.border(), 1)
                preferredSize = Dimension(100, 360)
            }, BorderLayout.CENTER)
            add(approvalPanel, BorderLayout.SOUTH)
        }
    }

    private fun buildHistoryCard(): JPanel {
        historyList.cellRenderer = SessionRenderer(timeFormatter)
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
                    add(JButton("Back").apply { addActionListener { showChatScreen() } }, BorderLayout.WEST)
                    add(JBLabel("History"), BorderLayout.CENTER)
                },
                BorderLayout.NORTH
            )
            add(JBScrollPane(historyList), BorderLayout.CENTER)
            add(JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
                isOpaque = false
                add(JButton("Open Chat").apply {
                    addActionListener { historyList.selectedValue?.let { activateSession(it.sessionId) } }
                })
            }, BorderLayout.SOUTH)
        }
        return root
    }

    private fun buildInput(): JPanel {
        inputArea.lineWrap = true
        inputArea.wrapStyleWord = true
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
        sendButton.preferredSize = Dimension(86, 34)
        sendButton.addActionListener { onSendOrStop() }
        updateSendButtonState()

        return JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.emptyTop(8)
            add(
                JPanel(BorderLayout()).apply {
                    isOpaque = false
                    border = JBUI.Borders.compound(
                        BorderFactory.createLineBorder(JBColor.border(), 1, true),
                        JBUI.Borders.empty(8)
                    )
                    add(JBScrollPane(inputArea).apply { border = JBUI.Borders.empty() }, BorderLayout.CENTER)
                    add(JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
                        isOpaque = false
                        add(sendButton)
                    }, BorderLayout.EAST)
                },
                BorderLayout.CENTER
            )
            add(statusLabel, BorderLayout.SOUTH)
        }
    }

    private fun headerButton(text: String, action: () -> Unit): JButton = JButton(text).apply {
        cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
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
                    statusLabel.text = "Message sent"
                    slashPopup?.cancel()
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
                statusLabel.text = "Session ${active.take(8)}"
            }
            startEventStreamAsync(active)
            refreshControlPlaneAsync()
        }
    }

    private fun ensureSessionBlocking(forceNew: Boolean): String? {
        if (!forceNew && !sessionId.isNullOrBlank()) return sessionId

        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath.orEmpty()
        if (projectRoot.isBlank()) {
            SwingUtilities.invokeLater { statusLabel.text = "Project root is empty" }
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
            if (forceNew || !created.reused) {
                SwingUtilities.invokeLater {
                    timelineModel.clear()
                    renderPendingApprovals(emptyList())
                }
            }
            created.sessionId
        } catch (ex: Exception) {
            logger.warn("Failed to create session", ex)
            SwingUtilities.invokeLater { statusLabel.text = "Failed to initialize session: ${ex.message}" }
            null
        }
    }

    private fun activateSession(targetSessionId: String) {
        sessionId = targetSessionId
        latestActivity = "idle"
        timelineModel.clear()
        renderPendingApprovals(emptyList())
        showChatScreen()
        startEventStreamAsync(targetSessionId)
        refreshControlPlaneAsync()
    }

    private fun loadSessionsHistoryAsync() {
        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath.orEmpty()
        if (projectRoot.isBlank()) {
            statusLabel.text = "Project root is empty"
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
                SwingUtilities.invokeLater { statusLabel.text = "History load failed: ${ex.message}" }
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
                    renderHistory(history)
                    renderStatus(status)
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) logger.debug("Refresh failed", ex)
            } finally {
                refreshInFlight.set(false)
            }
        }
    }

    private fun renderHistory(history: ChatHistoryResponseDto) {
        val lines = history.messages
            .filterNot { it.role.equals("assistant", ignoreCase = true) && it.content.trim().isBlank() }
            .sortedBy { it.createdAt }
            .map {
                when (it.role.lowercase()) {
                    "user" -> UiLine(UiLineKind.USER, it.content, it.createdAt)
                    "assistant" -> UiLine(UiLineKind.ASSISTANT, it.content, it.createdAt)
                    else -> UiLine(UiLineKind.SYSTEM, it.content, it.createdAt)
                }
            }

        timelineModel.clear()
        lines.forEach(timelineModel::addElement)
        if (timelineModel.size > 0) timeline.ensureIndexIsVisible(timelineModel.size - 1)
        renderPendingApprovals(history.pendingPermissions)
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
        statusLabel.text = "${status.sessionId.take(8)} | ${status.activity}"
    }

    private fun renderPendingApprovals(pending: List<ChatPendingPermissionDto>) {
        approvalPanel.removeAll()
        pending.forEach { permission ->
            val row = JPanel(BorderLayout()).apply {
                border = JBUI.Borders.compound(
                    BorderFactory.createLineBorder(JBColor.border(), 1, true),
                    JBUI.Borders.empty(8)
                )
                background = JBColor.PanelBackground
            }
            row.add(JBLabel("Approval: ${permission.title} (${permission.kind})"), BorderLayout.CENTER)
            row.add(JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                isOpaque = false
                add(JButton("Approve once").apply { addActionListener { submitApproval(permission, "approve_once") } })
                add(JButton("Approve always").apply { addActionListener { submitApproval(permission, "approve_always") } })
                add(JButton("Reject").apply { addActionListener { submitApproval(permission, "reject") } })
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

        ApplicationManager.getApplication().executeOnPooledThread {
            val base = settings.backendUrl.trimEnd('/')
            val request = Request.Builder().url("$base/chat/sessions/$activeSession/stream").get().build()
            val call = streamClient.newCall(request)
            streamCall = call
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) {
                        SwingUtilities.invokeLater { statusLabel.text = "Stream failed: HTTP ${response.code}" }
                        scheduleStreamReconnect(activeSession)
                        return@use
                    }
                    val source = response.body?.source() ?: run {
                        scheduleStreamReconnect(activeSession)
                        return@use
                    }
                    var hasData = false
                    while (!source.exhausted() && isDisplayable && sessionId == activeSession) {
                        val line = source.readUtf8Line() ?: break
                        when {
                            line.startsWith("data:") -> hasData = true
                            line.isBlank() && hasData -> {
                                hasData = false
                                refreshControlPlaneAsync()
                            }
                        }
                    }
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) logger.debug("Stream disconnected", ex)
                scheduleStreamReconnect(activeSession)
            } finally {
                if (streamCall == call) streamCall = null
            }
        }
    }

    private fun scheduleStreamReconnect(activeSession: String) {
        if (!isDisplayable || sessionId != activeSession) return
        ApplicationManager.getApplication().executeOnPooledThread {
            Thread.sleep(1200)
            if (isDisplayable && sessionId == activeSession) startEventStreamAsync(activeSession)
        }
    }

    private fun stopEventStream() {
        streamCall?.cancel()
        streamCall = null
        streamSessionId = null
    }

    private fun showHistoryScreen() {
        cardLayout.show(bodyCards, "history")
    }

    private fun showChatScreen() {
        cardLayout.show(bodyCards, "chat")
    }

    private fun isGenerating(): Boolean = latestActivity in setOf("busy", "retry", "waiting_permission")

    private fun updateSendButtonState() {
        if (isGenerating()) {
            sendButton.text = "Stop"
            sendButton.icon = AllIcons.Actions.Close
            sendButton.background = JBColor(Color(0xC9, 0x3C, 0x3C), Color(0xB3, 0x35, 0x35))
            sendButton.foreground = JBColor.WHITE
        } else {
            sendButton.text = "Send"
            sendButton.icon = AllIcons.Actions.Execute
            sendButton.background = JBColor.PanelBackground
            sendButton.foreground = JBColor.foreground()
        }
        sendButton.isOpaque = true
    }

    private fun appendSystemLine(text: String) {
        timelineModel.addElement(UiLine(UiLineKind.SYSTEM, text, Instant.now()))
        timeline.ensureIndexIsVisible(timelineModel.size - 1)
    }

    private fun upsertProgressLine(text: String) {
        val idx = (0 until timelineModel.size).firstOrNull { timelineModel.get(it).kind == UiLineKind.PROGRESS }
        if (idx == null) {
            timelineModel.addElement(UiLine(UiLineKind.PROGRESS, text, Instant.now()))
        } else {
            timelineModel.set(idx, UiLine(UiLineKind.PROGRESS, text, Instant.now()))
        }
        timeline.ensureIndexIsVisible(timelineModel.size - 1)
    }

    private fun removeProgressLine() {
        val idx = (0 until timelineModel.size).firstOrNull { timelineModel.get(it).kind == UiLineKind.PROGRESS } ?: return
        timelineModel.remove(idx)
    }

    private fun maybeShowSlashPopup() {
        val value = inputArea.text.trim()
        if (!value.startsWith("/")) {
            slashPopup?.cancel()
            slashPopup = null
            return
        }
        val token = value.removePrefix("/").lowercase()
        if (token.contains(" ")) {
            slashPopup?.cancel()
            slashPopup = null
            return
        }
        val matches = supportedCommands.filter { it.startsWith(token) }.map { "/$it" }
        if (matches.isEmpty()) {
            slashPopup?.cancel()
            slashPopup = null
            return
        }

        slashPopup?.cancel()
        val step = object : BaseListPopupStep<String>("Commands", matches) {
            override fun onChosen(selectedValue: String?, finalChoice: Boolean): PopupStep<*> {
                if (selectedValue != null) {
                    inputArea.text = selectedValue
                    inputArea.caretPosition = inputArea.text.length
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
        slashPopup = popup
        popup.show(RelativePoint.getSouthWestOf(inputArea))
    }

    private data class UiLine(val kind: UiLineKind, val text: String, val createdAt: Instant)

    private enum class UiLineKind {
        USER,
        ASSISTANT,
        SYSTEM,
        PROGRESS
    }

    private class BubbleRenderer : DefaultListCellRenderer() {
        override fun getListCellRendererComponent(
            list: JList<*>,
            value: Any?,
            index: Int,
            isSelected: Boolean,
            cellHasFocus: Boolean
        ): Component {
            val line = value as? UiLine ?: return super.getListCellRendererComponent(list, "", index, false, false)
            val text = line.text.replace("\n", "<br>")
            val html = "<html><body style='width:260px'>$text</body></html>"
            val label = super.getListCellRendererComponent(list, html, index, false, false) as DefaultListCellRenderer
            label.border = JBUI.Borders.empty(8, 10)
            label.isOpaque = true
            when (line.kind) {
                UiLineKind.USER -> {
                    label.background = JBColor(Color(0x2D, 0x6C, 0xD3), Color(0x2F, 0x5F, 0xA3))
                    label.foreground = JBColor.WHITE
                }
                UiLineKind.ASSISTANT -> {
                    label.background = JBColor(Color(0x44, 0x48, 0x53), Color(0x3C, 0x3F, 0x48))
                    label.foreground = JBColor.WHITE
                }
                UiLineKind.PROGRESS -> {
                    label.background = JBColor(Color(0x53, 0x56, 0x5F), Color(0x4A, 0x4D, 0x55))
                    label.foreground = JBColor(Color(0xD9, 0xDD, 0xE4), Color(0xD9, 0xDD, 0xE4))
                }
                UiLineKind.SYSTEM -> {
                    label.background = JBColor(Color(0x5B, 0x4D, 0x40), Color(0x4D, 0x43, 0x39))
                    label.foreground = JBColor(Color(0xE8, 0xDB, 0xCA), Color(0xE8, 0xDB, 0xCA))
                }
            }

            return JPanel(BorderLayout()).apply {
                isOpaque = false
                border = JBUI.Borders.empty(4, 8)
                if (line.kind == UiLineKind.USER) add(label, BorderLayout.EAST) else add(label, BorderLayout.WEST)
            }
        }
    }

    private class SessionRenderer(private val formatter: DateTimeFormatter) : DefaultListCellRenderer() {
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
            return super.getListCellRendererComponent(list, text, index, isSelected, cellHasFocus)
        }
    }
}

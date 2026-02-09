package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.icons.AllIcons
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.ui.JBUI
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.model.ChatCommandRequestDto
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatPendingPermissionDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatSessionDiffResponseDto
import ru.sber.aitestplugin.model.ChatSessionStatusResponseDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.FlowLayout
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.BoxLayout
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.SwingUtilities
import javax.swing.Timer

/**
 * Main agent ToolWindow focused on: current activity, cost, planned changes, and approvals.
 */
class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient()
) : JPanel(BorderLayout()) {
    private val logger = Logger.getInstance(AiToolWindowPanel::class.java)
    private val settings = AiTestPluginSettingsService.getInstance().settings
    private val refreshInFlight = AtomicBoolean(false)
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())
    private val streamClient = OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val pollTimer = Timer(1500) { refreshControlPlaneAsync() }

    private val timelineModel = DefaultListModel<String>()
    private val timeline = JBList(timelineModel)
    private val inputArea = JBTextArea(4, 20)
    private val changedFilesModel = DefaultListModel<String>()
    private val changedFilesList = JBList(changedFilesModel)

    private val activityBadge = JBLabel("State: idle")
    private val currentActionLabel = JBLabel("Action: Idle")
    private val activityDetailsLabel = JBLabel("Pending approvals: 0")
    private val costSummaryLabel = JBLabel("Tokens: 0 | Cost: 0.0000")
    private val limitSummaryLabel = JBLabel("Context: n/a")
    private val diffSummaryLabel = JBLabel("Diff: 0 files (+0/-0)")
    private val riskLabel = JBLabel("Risk: low")
    private val statusLabel = JBLabel("Connecting chat session...")

    private val approvalPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        border = JBUI.Borders.empty(8, 0)
    }

    private var sessionId: String? = null
    private var streamSessionId: String? = null
    private var streamCall: Call? = null

    init {
        border = JBUI.Borders.empty(8)
        background = JBColor.PanelBackground
        add(buildCenterPanel(), BorderLayout.CENTER)
        add(buildBottomPanel(), BorderLayout.SOUTH)
        ensureSessionAsync()
    }

    override fun addNotify() {
        super.addNotify()
        pollTimer.start()
        sessionId?.let { startEventStreamAsync(it) }
    }

    override fun removeNotify() {
        pollTimer.stop()
        stopEventStream()
        super.removeNotify()
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        appendLocalSystemMessage(
            "Legacy action: scan complete, steps=${response.stepsCount}, updated=${response.updatedAt}."
        )
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        appendLocalSystemMessage("Legacy action: unmapped steps=${unmappedSteps.size}.")
    }

    private fun buildCenterPanel(): JPanel {
        val center = JPanel(BorderLayout()).apply {
            background = JBColor.PanelBackground
        }
        val dashboard = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            isOpaque = false
            add(buildNowCard())
            add(buildCostCard())
            add(buildChangesCard())
        }
        timeline.emptyText.text = "Chat with automation agent and control it via commands."
        center.add(dashboard, BorderLayout.NORTH)
        center.add(JBScrollPane(timeline), BorderLayout.CENTER)
        center.add(approvalPanel, BorderLayout.SOUTH)
        return center
    }

    private fun buildNowCard(): JPanel =
        JPanel(BorderLayout()).apply {
            border = JBUI.Borders.compound(
                JBUI.Borders.customLine(JBColor.border(), 1),
                JBUI.Borders.empty(8)
            )
            isOpaque = false
            add(activityBadge, BorderLayout.NORTH)
            add(currentActionLabel, BorderLayout.CENTER)
            add(activityDetailsLabel, BorderLayout.SOUTH)
        }

    private fun buildCostCard(): JPanel =
        JPanel(BorderLayout()).apply {
            border = JBUI.Borders.compound(
                JBUI.Borders.customLine(JBColor.border(), 1),
                JBUI.Borders.empty(8)
            )
            isOpaque = false
            add(JBLabel("Cost and Usage"), BorderLayout.NORTH)
            add(costSummaryLabel, BorderLayout.CENTER)
            add(limitSummaryLabel, BorderLayout.SOUTH)
        }

    private fun buildChangesCard(): JPanel =
        JPanel(BorderLayout()).apply {
            border = JBUI.Borders.compound(
                JBUI.Borders.customLine(JBColor.border(), 1),
                JBUI.Borders.empty(8)
            )
            isOpaque = false
            add(JBLabel("Planned Changes"), BorderLayout.NORTH)
            add(
                JPanel(BorderLayout()).apply {
                    isOpaque = false
                    add(diffSummaryLabel, BorderLayout.NORTH)
                    add(riskLabel, BorderLayout.CENTER)
                    add(
                        JBScrollPane(changedFilesList).apply {
                            preferredSize = Dimension(100, 84)
                        },
                        BorderLayout.SOUTH
                    )
                },
                BorderLayout.CENTER
            )
        }

    private fun buildBottomPanel(): JPanel {
        val root = JPanel(BorderLayout()).apply {
            background = JBColor.PanelBackground
        }

        val chips = JPanel(FlowLayout(FlowLayout.LEFT, 6, 0)).apply {
            isOpaque = false
            add(createCommandButton("/status"))
            add(createCommandButton("/diff"))
            add(createCommandButton("/compact"))
            add(createCommandButton("/abort"))
            add(createCommandButton("/help"))
        }

        val inputWrap = JPanel(BorderLayout()).apply {
            isOpaque = false
            border = JBUI.Borders.empty(8, 0, 0, 0)
            inputArea.lineWrap = true
            inputArea.wrapStyleWord = true
            add(JBScrollPane(inputArea), BorderLayout.CENTER)
            add(
                JPanel(FlowLayout(FlowLayout.RIGHT, 0, 0)).apply {
                    isOpaque = false
                    add(
                        JButton("Send", AllIcons.Actions.Execute).apply {
                            addActionListener { submitInput(inputArea.text.trim()) }
                        }
                    )
                },
                BorderLayout.SOUTH
            )
        }

        root.add(chips, BorderLayout.NORTH)
        root.add(inputWrap, BorderLayout.CENTER)
        root.add(statusLabel, BorderLayout.SOUTH)
        return root
    }

    private fun createCommandButton(command: String): JButton =
        JButton(command).apply {
            addActionListener { submitInput(command) }
        }

    private fun ensureSessionAsync() {
        ApplicationManager.getApplication().executeOnPooledThread {
            val activeSession = ensureSessionBlocking() ?: return@executeOnPooledThread
            SwingUtilities.invokeLater {
                statusLabel.text = "Chat session ${activeSession.take(8)} is active."
            }
            startEventStreamAsync(activeSession)
            refreshControlPlaneAsync()
        }
    }

    private fun ensureSessionBlocking(): String? {
        if (!sessionId.isNullOrBlank()) {
            return sessionId
        }
        val projectRoot = settings.scanProjectRoot?.takeIf { it.isNotBlank() } ?: project.basePath.orEmpty()
        if (projectRoot.isBlank()) {
            SwingUtilities.invokeLater {
                statusLabel.text = "Project root is empty. Configure project path in settings."
            }
            return null
        }
        return try {
            val created = backendClient.createChatSession(
                ChatSessionCreateRequestDto(
                    projectRoot = projectRoot,
                    source = "ide-plugin",
                    profile = "quick",
                    reuseExisting = true
                )
            )
            sessionId = created.sessionId
            created.sessionId
        } catch (ex: Exception) {
            logger.warn("Failed to create chat session", ex)
            SwingUtilities.invokeLater {
                statusLabel.text = "Failed to initialize chat session: ${ex.message}"
            }
            null
        }
    }

    private fun submitInput(input: String) {
        if (input.isBlank()) return
        inputArea.text = ""

        val command = input.trim().lowercase()
        when (command) {
            "/status" -> submitControlCommand("status")
            "/diff" -> submitControlCommand("diff")
            "/compact" -> submitControlCommand("compact")
            "/abort" -> submitControlCommand("abort")
            "/help" -> {
                appendLocalSystemMessage("Commands: /status /diff /compact /abort /help")
                submitControlCommand("help")
            }
            else -> submitChatMessage(input)
        }
    }

    private fun submitChatMessage(message: String) {
        appendLocalUserMessage(message)
        ApplicationManager.getApplication().executeOnPooledThread {
            val activeSession = ensureSessionBlocking() ?: return@executeOnPooledThread
            try {
                backendClient.sendChatMessage(
                    activeSession,
                    ChatMessageRequestDto(content = message)
                )
                SwingUtilities.invokeLater {
                    statusLabel.text = "Message sent. Waiting for agent response..."
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to send chat message", ex)
                SwingUtilities.invokeLater {
                    statusLabel.text = "Message failed: ${ex.message}"
                }
            }
        }
    }

    private fun submitControlCommand(command: String) {
        appendLocalSystemMessage("Command: /$command")
        ApplicationManager.getApplication().executeOnPooledThread {
            val activeSession = ensureSessionBlocking() ?: return@executeOnPooledThread
            try {
                backendClient.executeChatCommand(activeSession, ChatCommandRequestDto(command = command))
                SwingUtilities.invokeLater {
                    statusLabel.text = "Command /$command accepted."
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to execute chat command", ex)
                SwingUtilities.invokeLater {
                    statusLabel.text = "Command /$command failed: ${ex.message}"
                }
            }
        }
    }

    private fun refreshControlPlaneAsync() {
        val activeSession = sessionId ?: return
        if (!refreshInFlight.compareAndSet(false, true)) {
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val history = backendClient.getChatHistory(activeSession)
                val status = backendClient.getChatStatus(activeSession)
                val diff = backendClient.getChatDiff(activeSession)
                SwingUtilities.invokeLater {
                    renderHistory(history)
                    renderStatus(status)
                    renderCost(status)
                    renderDiff(diff)
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) {
                    logger.debug("Control-plane refresh failed", ex)
                }
            } finally {
                refreshInFlight.set(false)
            }
        }
    }

    private fun renderHistory(history: ChatHistoryResponseDto) {
        timelineModel.clear()
        history.messages
            .sortedBy { it.createdAt }
            .forEach { message ->
                val time = timeFormatter.format(message.createdAt)
                val role = when (message.role.lowercase()) {
                    "assistant" -> "Agent"
                    "user" -> "You"
                    else -> message.role
                }
                timelineModel.addElement("$time [$role] ${message.content}")
            }
        if (timelineModel.size > 0) {
            timeline.ensureIndexIsVisible(timelineModel.size - 1)
        }
        renderPendingApprovals(history.pendingPermissions)
    }

    private fun renderStatus(status: ChatSessionStatusResponseDto) {
        activityBadge.text = "State: ${status.activity}"
        currentActionLabel.text = "Action: ${status.currentAction}"
        activityDetailsLabel.text = "Pending approvals: ${status.pendingPermissionsCount} | Updated: ${status.updatedAt}"
        statusLabel.text = "Session ${status.sessionId.take(8)} | ${status.activity} | risk=${status.risk.level}"
    }

    private fun renderCost(status: ChatSessionStatusResponseDto) {
        val tokens = status.totals.tokens
        val totalTokens = tokens.input + tokens.output + tokens.reasoning + tokens.cacheRead + tokens.cacheWrite
        costSummaryLabel.text = "Tokens: $totalTokens (in=${tokens.input}, out=${tokens.output}, reason=${tokens.reasoning}) | Cost: ${"%.4f".format(status.totals.cost)}"
        val context = status.limits.contextWindow
        val percent = status.limits.percent?.let { "%.2f".format(it) } ?: "n/a"
        limitSummaryLabel.text = if (context != null) {
            "Context: ${status.limits.used}/$context ($percent%)"
        } else {
            "Context: used=${status.limits.used} (window n/a)"
        }
    }

    private fun renderDiff(diff: ChatSessionDiffResponseDto) {
        diffSummaryLabel.text =
            "Diff: ${diff.summary.files} files (+${diff.summary.additions}/-${diff.summary.deletions})"
        val reasons = if (diff.risk.reasons.isNotEmpty()) diff.risk.reasons.joinToString("; ") else "n/a"
        riskLabel.text = "Risk: ${diff.risk.level} | $reasons"

        changedFilesModel.clear()
        if (diff.files.isEmpty()) {
            changedFilesModel.addElement("No file changes yet.")
            return
        }
        diff.files.forEach { file ->
            changedFilesModel.addElement("${file.file} (+${file.additions}/-${file.deletions})")
        }
    }

    private fun renderPendingApprovals(pendingPermissions: List<ChatPendingPermissionDto>) {
        approvalPanel.removeAll()
        pendingPermissions.forEach { permission ->
            val row = JPanel(BorderLayout()).apply {
                border = JBUI.Borders.compound(
                    JBUI.Borders.customLine(JBColor.border(), 1),
                    JBUI.Borders.empty(6)
                )
                background = JBColor.PanelBackground
            }
            val details = JBLabel("Approval required: ${permission.title} (kind=${permission.kind})")
            row.add(details, BorderLayout.CENTER)
            row.add(
                JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                    isOpaque = false
                    add(
                        JButton("Approve once").apply {
                            addActionListener { submitPermissionDecision(permission, "approve_once") }
                        }
                    )
                    add(
                        JButton("Approve always").apply {
                            addActionListener { submitPermissionDecision(permission, "approve_always") }
                        }
                    )
                    add(
                        JButton("Reject").apply {
                            addActionListener { submitPermissionDecision(permission, "reject") }
                        }
                    )
                },
                BorderLayout.EAST
            )
            approvalPanel.add(row)
        }
        approvalPanel.revalidate()
        approvalPanel.repaint()
    }

    private fun submitPermissionDecision(permission: ChatPendingPermissionDto, decision: String) {
        val activeSession = sessionId ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                backendClient.submitChatToolDecision(
                    activeSession,
                    ChatToolDecisionRequestDto(
                        permissionId = permission.permissionId,
                        decision = decision
                    )
                )
                SwingUtilities.invokeLater {
                    statusLabel.text = "Decision $decision sent for ${permission.title}."
                }
                refreshControlPlaneAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to submit tool decision", ex)
                SwingUtilities.invokeLater {
                    statusLabel.text = "Decision failed: ${ex.message}"
                }
            }
        }
    }

    private fun startEventStreamAsync(activeSession: String) {
        if (streamSessionId == activeSession && streamCall != null) {
            return
        }
        stopEventStream()
        streamSessionId = activeSession
        ApplicationManager.getApplication().executeOnPooledThread {
            val base = settings.backendUrl.trimEnd('/')
            val request = Request.Builder()
                .url("$base/chat/sessions/$activeSession/stream")
                .get()
                .build()
            val call = streamClient.newCall(request)
            streamCall = call
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) {
                        SwingUtilities.invokeLater {
                            statusLabel.text = "Stream failed: HTTP ${response.code}"
                        }
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
                            line.isBlank() -> {
                                if (hasData) {
                                    hasData = false
                                    refreshControlPlaneAsync()
                                }
                            }
                        }
                    }
                }
            } catch (ex: Exception) {
                if (logger.isDebugEnabled) {
                    logger.debug("Chat stream disconnected", ex)
                }
                scheduleStreamReconnect(activeSession)
            } finally {
                if (streamCall == call) {
                    streamCall = null
                }
            }
        }
    }

    private fun scheduleStreamReconnect(activeSession: String) {
        if (!isDisplayable || sessionId != activeSession) {
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            Thread.sleep(1200)
            if (isDisplayable && sessionId == activeSession) {
                startEventStreamAsync(activeSession)
            }
        }
    }

    private fun stopEventStream() {
        streamCall?.cancel()
        streamCall = null
        streamSessionId = null
    }

    private fun appendLocalUserMessage(content: String) {
        val time = timeFormatter.format(java.time.Instant.now())
        timelineModel.addElement("$time [You] $content")
        timeline.ensureIndexIsVisible(timelineModel.size - 1)
    }

    private fun appendLocalSystemMessage(content: String) {
        val time = timeFormatter.format(java.time.Instant.now())
        timelineModel.addElement("$time [System] $content")
        timeline.ensureIndexIsVisible(timelineModel.size - 1)
    }
}

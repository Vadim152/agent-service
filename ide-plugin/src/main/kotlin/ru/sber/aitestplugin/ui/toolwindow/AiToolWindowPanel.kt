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
import ru.sber.aitestplugin.config.AiTestPluginSettingsService
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatPendingToolCallDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.UnmappedStepDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.services.HttpBackendClient
import java.awt.BorderLayout
import java.awt.FlowLayout
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.BoxLayout
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.SwingUtilities
import javax.swing.Timer

/**
 * Chat-only Tool Window panel.
 */
class AiToolWindowPanel(
    private val project: Project,
    private val backendClient: BackendClient = HttpBackendClient()
) : JPanel(BorderLayout()) {
    private val logger = Logger.getInstance(AiToolWindowPanel::class.java)
    private val settings = AiTestPluginSettingsService.getInstance().settings
    private val timelineModel = DefaultListModel<String>()
    private val timeline = JBList(timelineModel)
    private val inputArea = JBTextArea(4, 20)
    private val statusLabel = JBLabel("Connecting chat session...")
    private val approvalPanel = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        border = JBUI.Borders.empty(8, 0)
    }
    private val refreshInFlight = AtomicBoolean(false)
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())
    private var sessionId: String? = null
    private val pollTimer = Timer(1500) { refreshHistoryAsync() }

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
    }

    override fun removeNotify() {
        pollTimer.stop()
        super.removeNotify()
    }

    fun showScanResult(response: ScanStepsResponseDto) {
        appendLocalSystemMessage(
            "Legacy action: scan complete, steps=${response.stepsCount}, updated=${response.updatedAt}."
        )
    }

    fun showUnmappedSteps(unmappedSteps: List<UnmappedStepDto>) {
        appendLocalSystemMessage(
            "Legacy action: unmapped steps=${unmappedSteps.size}."
        )
    }

    private fun buildCenterPanel(): JPanel {
        val panel = JPanel(BorderLayout())
        panel.background = JBColor.PanelBackground

        timeline.emptyText.text = "Chat with automation agent. Try /scan-steps or /generate-test <text>."
        panel.add(JBScrollPane(timeline), BorderLayout.CENTER)
        panel.add(approvalPanel, BorderLayout.SOUTH)
        return panel
    }

    private fun buildBottomPanel(): JPanel {
        val root = JPanel(BorderLayout())
        root.background = JBColor.PanelBackground

        val chips = JPanel(FlowLayout(FlowLayout.LEFT, 6, 0)).apply {
            isOpaque = false
            add(createCommandButton("/scan-steps"))
            add(createCommandButton("/generate-test"))
            add(createCommandButton("/new-automation"))
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
                            addActionListener { submitMessage(inputArea.text.trim()) }
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
            addActionListener {
                when (command) {
                    "/generate-test" -> submitMessage("$command Given user opens home page")
                    "/new-automation" -> submitMessage("$command Create automation from smoke user flow")
                    else -> submitMessage(command)
                }
            }
        }

    private fun ensureSessionAsync() {
        ApplicationManager.getApplication().executeOnPooledThread {
            val session = ensureSessionBlocking() ?: return@executeOnPooledThread
            SwingUtilities.invokeLater {
                statusLabel.text = "Chat session ${session.take(8)} is active."
            }
            refreshHistoryAsync()
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

    private fun submitMessage(message: String) {
        if (message.isBlank()) return
        inputArea.text = ""
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
                refreshHistoryAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to send chat message", ex)
                SwingUtilities.invokeLater {
                    statusLabel.text = "Message failed: ${ex.message}"
                }
            }
        }
    }

    private fun refreshHistoryAsync() {
        val activeSession = sessionId ?: return
        if (!refreshInFlight.compareAndSet(false, true)) {
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val history = backendClient.getChatHistory(activeSession)
                SwingUtilities.invokeLater { renderHistory(history) }
            } catch (_: Exception) {
                // Keep silent here to avoid noisy status flickering during temporary outages.
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
        renderPendingApprovals(history.pendingToolCalls)
        statusLabel.text = "Session ${history.sessionId.take(8)} • ${history.status} • messages ${history.messages.size}"
    }

    private fun renderPendingApprovals(pendingCalls: List<ChatPendingToolCallDto>) {
        approvalPanel.removeAll()
        pendingCalls.forEach { call ->
            val row = JPanel(BorderLayout()).apply {
                border = JBUI.Borders.compound(
                    JBUI.Borders.customLine(JBColor.border(), 1),
                    JBUI.Borders.empty(6)
                )
                background = JBColor.PanelBackground
            }
            val details = JBLabel(
                "Approval required: ${call.toolName} (risk=${call.riskLevel}) args=${call.args}"
            )
            row.add(details, BorderLayout.CENTER)
            row.add(
                JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply {
                    isOpaque = false
                    add(
                        JButton("Approve").apply {
                            addActionListener { submitToolDecision(call, "approve") }
                        }
                    )
                    add(
                        JButton("Reject").apply {
                            addActionListener { submitToolDecision(call, "reject") }
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

    private fun submitToolDecision(call: ChatPendingToolCallDto, decision: String) {
        val activeSession = sessionId ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                backendClient.submitChatToolDecision(
                    activeSession,
                    ChatToolDecisionRequestDto(
                        toolCallId = call.toolCallId,
                        decision = decision
                    )
                )
                SwingUtilities.invokeLater {
                    statusLabel.text = "Decision `$decision` sent for ${call.toolName}."
                }
                refreshHistoryAsync()
            } catch (ex: Exception) {
                logger.warn("Failed to submit tool decision", ex)
                SwingUtilities.invokeLater {
                    statusLabel.text = "Decision failed: ${ex.message}"
                }
            }
        }
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

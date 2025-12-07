package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.openapi.project.Project
import com.intellij.ui.JBSplitter
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.StepDefinitionDto
import java.awt.BorderLayout
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel

/**
 * Основная панель Tool Window с кнопкой сканирования и таблицей шагов.
 */
class AiToolWindowPanel(private val project: Project) : JPanel(BorderLayout()) {
    private val scanButton = JButton("Scan steps")
    private val projectRootField = JBTextField(project.basePath ?: "")
    private val stepsList = JBList<StepDefinitionDto>()
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

        val listWrapper = JBScrollPane(stepsList)
        val splitter = JBSplitter(true, 0.8f).apply {
            firstComponent = listWrapper
            secondComponent = statusLabel
        }

        add(topPanel, BorderLayout.NORTH)
        add(splitter, BorderLayout.CENTER)

        scanButton.addActionListener {
            // TODO: запуск фоновой задачи scanSteps через BackendClient
            statusLabel.text = "Scanning..."
        }
    }
}

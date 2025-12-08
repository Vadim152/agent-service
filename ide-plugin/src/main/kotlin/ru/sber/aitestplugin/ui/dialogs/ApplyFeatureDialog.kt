package ru.sber.aitestplugin.ui.dialogs

import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel

/**
 * Диалог ввода параметров применения feature-файла.
 */
class ApplyFeatureDialog(project: Project, defaultTargetPath: String? = null) : DialogWrapper(project) {
    private val targetPathField = JBTextField(defaultTargetPath ?: "")
    private val overwriteCheckbox = JBCheckBox("Overwrite existing file", false)

    init {
        title = "Apply Feature"
        init()
    }

    override fun createCenterPanel(): JComponent {
        val panel = JPanel(GridBagLayout())
        panel.border = JBUI.Borders.empty(8)

        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            anchor = GridBagConstraints.WEST
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
            ipadx = 4
            ipady = 4
        }

        panel.add(JLabel("Target path (relative to project root):"), gbc)
        gbc.gridy++
        panel.add(targetPathField, gbc)

        gbc.gridy++
        panel.add(overwriteCheckbox, gbc)

        return panel
    }

    fun targetPath(): String? = targetPathField.text.trim().takeIf { it.isNotEmpty() }

    fun shouldOverwriteExisting(): Boolean = overwriteCheckbox.isSelected
}

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
 * Диалог ввода опций генерации feature.
 */
class GenerateFeatureDialog(project: Project, defaults: GenerateFeatureDialogOptions) : DialogWrapper(project) {
    private val targetPathField = JBTextField(defaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox("Create file if missing", defaults.createFile)
    private val overwriteCheckbox = JBCheckBox("Overwrite existing file", defaults.overwriteExisting)
    private val languageField = JBTextField()

    init {
        title = "Generate Feature"
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
        panel.add(createFileCheckbox, gbc)

        gbc.gridy++
        panel.add(overwriteCheckbox, gbc)

        gbc.gridy++
        panel.add(JLabel("Language (optional):"), gbc)
        gbc.gridy++
        panel.add(languageField, gbc)

        return panel
    }

    fun targetPath(): String? = targetPathField.text.trim().takeIf { it.isNotEmpty() }

    fun shouldCreateFile(): Boolean = createFileCheckbox.isSelected

    fun shouldOverwriteExisting(): Boolean = overwriteCheckbox.isSelected

    fun selectedOptions(): GenerateFeatureDialogOptions = GenerateFeatureDialogOptions(
        targetPath = targetPath(),
        createFile = shouldCreateFile(),
        overwriteExisting = shouldOverwriteExisting()
    )

    fun language(): String? = languageField.text.trim().takeIf { it.isNotEmpty() }
}

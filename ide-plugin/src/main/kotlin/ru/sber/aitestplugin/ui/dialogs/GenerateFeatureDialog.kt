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
    private val createFileCheckbox = JBCheckBox("Создать файл, если отсутствует", defaults.createFile).apply {
        toolTipText = "Если путь не существует, будет создан новый файл"
        border = JBUI.Borders.emptyLeft(2)
    }
    private val overwriteCheckbox = JBCheckBox("Перезаписать существующий файл", defaults.overwriteExisting).apply {
        toolTipText = "При совпадении пути перезапишет найденный файл"
        border = JBUI.Borders.emptyLeft(2)
    }
    private val defaultLanguage = defaults.language

    init {
        title = "Сгенерировать feature"
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
            insets = JBUI.insetsBottom(8)
        }

        panel.add(JLabel("Целевой путь (относительно корня проекта)"), gbc)
        gbc.gridy++
        panel.add(targetPathField, gbc)

        gbc.gridy++
        panel.add(hintLabel("Пример: src/test/resources/features"), gbc)

        gbc.gridy++
        panel.add(createFileCheckbox, gbc)

        gbc.gridy++
        panel.add(overwriteCheckbox, gbc)

        return panel
    }

    fun targetPath(): String? = targetPathField.text.trim().takeIf { it.isNotEmpty() }

    fun shouldCreateFile(): Boolean = createFileCheckbox.isSelected

    fun shouldOverwriteExisting(): Boolean = overwriteCheckbox.isSelected

    fun selectedOptions(): GenerateFeatureDialogOptions = GenerateFeatureDialogOptions(
        targetPath = targetPath(),
        createFile = shouldCreateFile(),
        overwriteExisting = shouldOverwriteExisting(),
        language = defaultLanguage,
    )

}

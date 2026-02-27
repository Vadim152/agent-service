package ru.sber.aitestplugin.ui.dialogs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.GenerationResolvePreviewRequestDto
import ru.sber.aitestplugin.model.GenerationResolvePreviewResponseDto
import ru.sber.aitestplugin.services.BackendClient
import java.awt.Font
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel

/**
 * Dialog for feature generation options plus memory preview.
 */
class GenerateFeatureDialog(
    project: Project,
    defaults: GenerateFeatureDialogOptions,
    private val backendClient: BackendClient,
    private val projectRoot: String,
    private val testCaseText: String
) : DialogWrapper(project) {
    private val targetPathField = JBTextField(defaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox("Create file if it does not exist", defaults.createFile).apply {
        toolTipText = "If the target path is missing, the plugin will create a new feature file"
        border = JBUI.Borders.emptyLeft(2)
    }
    private val overwriteCheckbox = JBCheckBox("Overwrite existing file", defaults.overwriteExisting).apply {
        toolTipText = "Overwrite the target feature file when it already exists"
        border = JBUI.Borders.emptyLeft(2)
    }
    private val defaultLanguage = defaults.language
    private val memoryStatusLabel = JLabel("Loading memory preview...")
    private val memoryPreviewArea = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(8)
        background = JBColor.PanelBackground
        foreground = JBColor.foreground()
        font = font.deriveFont(Font.PLAIN, font.size2D)
        rows = 7
    }
    private val refreshPreviewButton = JButton("Refresh Preview")
    private var latestPreview: GenerationResolvePreviewResponseDto? = null

    init {
        title = "Generate Feature"
        init()
        loadMemoryPreviewAsync()
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

        panel.add(JLabel("Target path (relative to project root)"), gbc)
        gbc.gridy++
        panel.add(targetPathField, gbc)

        gbc.gridy++
        panel.add(hintLabel("Example: src/test/resources/features/generated"), gbc)

        gbc.gridy++
        panel.add(createFileCheckbox, gbc)

        gbc.gridy++
        panel.add(overwriteCheckbox, gbc)

        gbc.gridy++
        panel.add(sectionLabel("Memory Preview"), gbc)

        gbc.gridy++
        panel.add(memoryStatusLabel, gbc)

        gbc.gridy++
        panel.add(memoryPreviewArea, gbc)

        gbc.gridy++
        gbc.weightx = 0.0
        panel.add(refreshPreviewButton.apply { addActionListener { loadMemoryPreviewAsync() } }, gbc)

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

    private fun loadMemoryPreviewAsync() {
        memoryStatusLabel.text = "Loading memory preview..."
        memoryPreviewArea.text = ""
        refreshPreviewButton.isEnabled = false
        ApplicationManager.getApplication().executeOnPooledThread {
            val request = GenerationResolvePreviewRequestDto(
                projectRoot = projectRoot,
                text = testCaseText,
                language = defaultLanguage,
                qualityPolicy = DEFAULT_QUALITY_POLICY,
            )
            runCatching { backendClient.resolveGenerationPreview(request) }
                .onSuccess { preview ->
                    ApplicationManager.getApplication().invokeLater {
                        refreshPreviewButton.isEnabled = true
                        latestPreview = preview
                        if (targetPathField.text.trim().isEmpty() && !preview.targetPath.isNullOrBlank()) {
                            targetPathField.text = preview.targetPath
                        }
                        memoryStatusLabel.text = buildMemoryPreviewStatus(preview)
                        memoryPreviewArea.text = formatMemoryPreview(preview)
                    }
                }
                .onFailure { ex ->
                    ApplicationManager.getApplication().invokeLater {
                        refreshPreviewButton.isEnabled = true
                        latestPreview = null
                        memoryStatusLabel.text = "Memory preview unavailable"
                        memoryPreviewArea.text = ex.message?.trim().takeUnless { it.isNullOrBlank() }
                            ?: "The backend did not return memory preview data. Generation can continue without it."
                    }
                }
        }
    }

    private fun hintLabel(text: String): JLabel = JLabel(text).apply {
        border = JBUI.Borders.emptyLeft(2)
    }

    private fun sectionLabel(text: String): JLabel = JLabel(text).apply {
        font = font.deriveFont(Font.BOLD)
    }

    companion object {
        private const val DEFAULT_QUALITY_POLICY = "strict"
    }
}

internal fun buildMemoryPreviewStatus(preview: GenerationResolvePreviewResponseDto): String {
    if (
        preview.appliedRuleIds.isEmpty() &&
        preview.appliedTemplateIds.isEmpty() &&
        preview.templateSteps.isEmpty() &&
        preview.targetPath.isNullOrBlank() &&
        preview.qualityPolicy.isNullOrBlank() &&
        preview.language.isNullOrBlank()
    ) {
        return "No memory rules matched this test case."
    }
    return "Memory rules will be applied automatically."
}

internal fun formatMemoryPreview(preview: GenerationResolvePreviewResponseDto): String {
    val lines = mutableListOf<String>()
    lines += "Matched rules: ${preview.appliedRuleIds.size}"
    lines += "Matched templates: ${preview.appliedTemplateIds.size}"
    lines += "Template steps to inject: ${preview.templateSteps.size}"
    preview.qualityPolicy?.takeIf { it.isNotBlank() }?.let { lines += "Effective quality policy: $it" }
    preview.language?.takeIf { it.isNotBlank() }?.let { lines += "Effective language: $it" }
    preview.targetPath?.takeIf { it.isNotBlank() }?.let { lines += "Suggested target path: $it" }
    if (preview.templateSteps.isNotEmpty()) {
        lines += ""
        lines += "Injected steps:"
        preview.templateSteps.forEachIndexed { index, step ->
            lines += "${index + 1}. $step"
        }
    } else {
        lines += ""
        lines += "No template steps will be injected."
    }
    return lines.joinToString("\n")
}

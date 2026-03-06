package ru.sber.aitestplugin.ui.dialogs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.ui.dsl.builder.Align
import com.intellij.ui.dsl.builder.AlignX
import com.intellij.ui.dsl.builder.panel
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.GenerationPreviewRequestDto
import ru.sber.aitestplugin.model.GenerationPreviewResponseDto
import ru.sber.aitestplugin.model.GenerationResolvePreviewResponseDto
import ru.sber.aitestplugin.model.SimilarScenarioDto
import ru.sber.aitestplugin.services.BackendClient
import ru.sber.aitestplugin.ui.UiStrings
import javax.swing.JButton
import javax.swing.JComboBox
import javax.swing.JComponent

class GenerateFeatureDialog(
    project: Project,
    defaults: GenerateFeatureDialogOptions,
    private val backendClient: BackendClient,
    private val projectRoot: String,
    private val testCaseText: String
) : DialogWrapper(project) {
    private val targetPathField = JBTextField(defaults.targetPath ?: "")
    private val createFileCheckbox = JBCheckBox(UiStrings.dialogCreateFile, false)
    private val overwriteCheckbox = JBCheckBox(UiStrings.dialogOverwriteFile, defaults.overwriteExisting)
    private val defaultLanguage = defaults.language
    private val previewStatusLabel = javax.swing.JLabel(UiStrings.dialogLoadingPreview)
    private val previewArea = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(8)
        background = JBColor.PanelBackground
        foreground = JBColor.foreground()
        rows = 14
    }
    private val scenarioSelector = JComboBox<String>()
    private val refreshPreviewButton = JButton(UiStrings.dialogRefreshPreview)
    private var latestPreview: GenerationPreviewResponseDto? = null
    private var similarScenarios: List<SimilarScenarioDto> = emptyList()

    init {
        title = UiStrings.generateFeatureTitle
        createFileCheckbox.isEnabled = false
        createFileCheckbox.toolTipText = "Draft is created in the editor. Save to disk via Apply after review."
        scenarioSelector.isEnabled = false
        scenarioSelector.addActionListener {
            previewStatusLabel.text = buildGenerationPreviewStatus(latestPreview, selectedScenario())
            latestPreview?.let { preview ->
                previewArea.text = formatGenerationPreview(preview, selectedScenario())
            }
        }
        refreshPreviewButton.addActionListener { loadPreviewAsync() }
        init()
        loadPreviewAsync()
    }

    override fun createCenterPanel(): JComponent = buildGenerateFeatureFormPanel(
        targetPathField = targetPathField,
        createFileCheckbox = createFileCheckbox,
        overwriteCheckbox = overwriteCheckbox,
        previewStatusLabel = previewStatusLabel,
        scenarioSelector = scenarioSelector,
        previewArea = previewArea,
        refreshPreviewButton = refreshPreviewButton,
    )

    fun targetPath(): String? = targetPathField.text.trim().takeIf { it.isNotEmpty() }

    fun shouldCreateFile(): Boolean = false

    fun shouldOverwriteExisting(): Boolean = overwriteCheckbox.isSelected

    fun selectedOptions(): GenerateFeatureDialogOptions = GenerateFeatureDialogOptions(
        targetPath = targetPath(),
        createFile = false,
        overwriteExisting = shouldOverwriteExisting(),
        language = defaultLanguage,
    )

    fun selectedScenarioId(): String? = selectedScenario()?.scenarioId ?: latestPreview?.generationPlan?.selectedScenarioId

    fun planId(): String? = latestPreview?.planId

    private fun selectedScenario(): SimilarScenarioDto? {
        val index = scenarioSelector.selectedIndex
        return if (index in similarScenarios.indices) similarScenarios[index] else null
    }

    private fun loadPreviewAsync() {
        previewStatusLabel.text = UiStrings.dialogLoadingPreview
        previewArea.text = ""
        scenarioSelector.removeAllItems()
        scenarioSelector.isEnabled = false
        refreshPreviewButton.isEnabled = false
        ApplicationManager.getApplication().executeOnPooledThread {
            val request = GenerationPreviewRequestDto(
                projectRoot = projectRoot,
                testCaseText = testCaseText,
                language = defaultLanguage,
                qualityPolicy = DEFAULT_QUALITY_POLICY,
            )
            runCatching { backendClient.previewGenerationPlan(request) }
                .onSuccess { preview ->
                    ApplicationManager.getApplication().invokeLater {
                        refreshPreviewButton.isEnabled = true
                        latestPreview = preview
                        similarScenarios = preview.similarScenarios
                        if (targetPathField.text.trim().isEmpty()) {
                            val memoryPath = preview.memoryPreview?.get("targetPath")?.toString()
                            if (!memoryPath.isNullOrBlank()) {
                                targetPathField.text = memoryPath
                            }
                        }
                        populateScenarioSelector(preview)
                        previewStatusLabel.text = buildGenerationPreviewStatus(preview, selectedScenario())
                        previewArea.text = formatGenerationPreview(preview, selectedScenario())
                    }
                }
                .onFailure { ex ->
                    ApplicationManager.getApplication().invokeLater {
                        refreshPreviewButton.isEnabled = true
                        latestPreview = null
                        similarScenarios = emptyList()
                        previewStatusLabel.text = UiStrings.dialogPreviewUnavailable
                        previewArea.text = ex.message?.trim().takeUnless { it.isNullOrBlank() }
                            ?: "Backend did not return a generation preview. You can still run draft generation."
                    }
                }
        }
    }

    private fun populateScenarioSelector(preview: GenerationPreviewResponseDto) {
        scenarioSelector.removeAllItems()
        similarScenarios = preview.similarScenarios
        similarScenarios.forEach { item ->
            val marker = if (item.recommended) "Recommended" else "Candidate"
            scenarioSelector.addItem("$marker: ${item.name} (${String.format("%.2f", item.score)})")
        }
        val selectedIndex = similarScenarios.indexOfFirst { it.recommended }.takeIf { it >= 0 } ?: 0
        if (similarScenarios.isNotEmpty()) {
            scenarioSelector.selectedIndex = selectedIndex
            scenarioSelector.isEnabled = true
        } else {
            scenarioSelector.isEnabled = false
        }
    }

    companion object {
        private const val DEFAULT_QUALITY_POLICY = "strict"
    }
}

internal fun buildGenerateFeatureFormPanel(
    targetPathField: JBTextField,
    createFileCheckbox: JBCheckBox,
    overwriteCheckbox: JBCheckBox,
    previewStatusLabel: javax.swing.JLabel,
    scenarioSelector: JComboBox<String>,
    previewArea: JBTextArea,
    refreshPreviewButton: JButton,
): JComponent = panel {
    row(UiStrings.dialogTargetPath) {
        cell(targetPathField).resizableColumn().align(AlignX.FILL)
    }
    row {
        comment(UiStrings.dialogTargetPathComment)
    }
    row {
        cell(createFileCheckbox)
    }
    row {
        cell(overwriteCheckbox)
    }
    group("Preview") {
        row {
            cell(previewStatusLabel)
        }
        row("Base scenario") {
            cell(scenarioSelector).resizableColumn().align(AlignX.FILL)
        }
        row {
            cell(JBScrollPane(previewArea))
                .resizableColumn()
                .align(Align.FILL)
        }
        row {
            cell(refreshPreviewButton)
        }
    }
}

internal fun buildGenerateFeatureFormPanel(
    targetPathField: JBTextField,
    createFileCheckbox: JBCheckBox,
    overwriteCheckbox: JBCheckBox,
    memoryStatusLabel: javax.swing.JLabel,
    memoryPreviewArea: JBTextArea,
    refreshPreviewButton: JButton,
): JComponent = buildGenerateFeatureFormPanel(
    targetPathField = targetPathField,
    createFileCheckbox = createFileCheckbox,
    overwriteCheckbox = overwriteCheckbox,
    previewStatusLabel = memoryStatusLabel,
    scenarioSelector = JComboBox(),
    previewArea = memoryPreviewArea,
    refreshPreviewButton = refreshPreviewButton,
)

internal fun buildGenerationPreviewStatus(
    preview: GenerationPreviewResponseDto?,
    selectedScenario: SimilarScenarioDto?
): String {
    if (preview == null) {
        return "Preview is unavailable."
    }
    val scenarioPart = selectedScenario?.name ?: "no base scenario"
    val warnings = preview.warnings.size
    return "Plan ${preview.planId ?: "-"}; base: $scenarioPart; warnings: $warnings"
}

internal fun formatGenerationPreview(
    preview: GenerationPreviewResponseDto,
    selectedScenario: SimilarScenarioDto?
): String {
    val lines = mutableListOf<String>()
    preview.canonicalTestCase?.let { canonical ->
        lines += "Canonical testcase"
        lines += "Title: ${canonical.title}"
        lines += "Preconditions: ${canonical.preconditions.size}"
        lines += "Actions: ${canonical.actions.size}"
        lines += "Expected results: ${canonical.expectedResults.size}"
        if (canonical.testData.isNotEmpty()) {
            lines += "Test data: ${canonical.testData.joinToString(", ")}"
        }
        lines += ""
    }

    lines += "Similar scenarios"
    if (preview.similarScenarios.isEmpty()) {
        lines += "No local .feature scenarios matched."
    } else {
        preview.similarScenarios.forEachIndexed { index, item ->
            val marker = if (item.recommended) "recommended" else "candidate"
            lines += "${index + 1}. [$marker] ${item.name} (${String.format("%.2f", item.score)})"
            if (item.matchedFragments.isNotEmpty()) {
                lines += "   matched: ${item.matchedFragments.joinToString(" | ")}"
            }
        }
    }

    lines += ""
    lines += "Generation plan"
    lines += "Selected scenario: ${selectedScenario?.name ?: preview.generationPlan.selectedScenarioId ?: "-"}"
    lines += "Candidate background steps: ${preview.generationPlan.candidateBackground.size}"
    lines += "Planned steps: ${preview.generationPlan.items.size}"
    if (preview.generationPlan.items.isNotEmpty()) {
        preview.generationPlan.items.forEach { item ->
            val selected = item.selectedStepId ?: "unmatched"
            val confidence = item.selectedConfidence?.let { String.format("%.2f", it) } ?: "-"
            lines += "${item.order}. [${item.intentType}] ${item.text}"
            lines += "   selected: $selected (confidence: $confidence)"
        }
    }

    if (preview.warnings.isNotEmpty()) {
        lines += ""
        lines += "Warnings"
        preview.warnings.forEach { warning ->
            lines += "- $warning"
        }
    }

    if (preview.quality != null) {
        lines += ""
        lines += "Quality gate"
        lines += "Score: ${preview.quality.score}"
        lines += "Passed: ${preview.quality.passed}"
        if (preview.quality.failures.isNotEmpty()) {
            lines += "Failures: ${preview.quality.failures.joinToString { it.code }}"
        }
        if (preview.quality.warnings.isNotEmpty()) {
            lines += "Quality warnings: ${preview.quality.warnings.joinToString { it.code }}"
        }
    }

    return lines.joinToString("\n")
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
        return "Правила памяти не сработали для этого тест-кейса."
    }
    return "Правила памяти будут применены автоматически."
}

internal fun formatMemoryPreview(preview: GenerationResolvePreviewResponseDto): String {
    val lines = mutableListOf<String>()
    lines += "Совпавших правил: ${preview.appliedRuleIds.size}"
    lines += "Совпавших шаблонов: ${preview.appliedTemplateIds.size}"
    lines += "Шагов для вставки: ${preview.templateSteps.size}"
    preview.qualityPolicy?.takeIf { it.isNotBlank() }?.let { lines += "Итоговая quality policy: $it" }
    preview.language?.takeIf { it.isNotBlank() }?.let { lines += "Итоговый язык: $it" }
    preview.targetPath?.takeIf { it.isNotBlank() }?.let { lines += "Рекомендуемый путь: $it" }
    if (preview.templateSteps.isNotEmpty()) {
        lines += ""
        lines += "Будут добавлены шаги:"
        preview.templateSteps.forEachIndexed { index, step ->
            lines += "${index + 1}. $step"
        }
    } else {
        lines += ""
        lines += "Шаблонные шаги не будут добавлены."
    }
    return lines.joinToString("\n")
}

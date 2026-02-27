package ru.sber.aitestplugin.ui.dialogs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.openapi.ui.Messages
import com.intellij.ui.JBColor
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.components.JBTextField
import com.intellij.ui.dsl.builder.panel
import com.intellij.util.ui.JBUI
import ru.sber.aitestplugin.model.GenerationRuleActionsDto
import ru.sber.aitestplugin.model.GenerationRuleConditionDto
import ru.sber.aitestplugin.model.GenerationRuleCreateRequestDto
import ru.sber.aitestplugin.model.GenerationRuleDto
import ru.sber.aitestplugin.model.GenerationRulePatchRequestDto
import ru.sber.aitestplugin.model.StepTemplateCreateRequestDto
import ru.sber.aitestplugin.model.StepTemplateDto
import ru.sber.aitestplugin.model.StepTemplatePatchRequestDto
import ru.sber.aitestplugin.services.BackendClient
import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.GridLayout
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JCheckBox
import javax.swing.JComboBox
import javax.swing.JComponent
import javax.swing.JList
import javax.swing.JOptionPane
import javax.swing.JPanel
import javax.swing.JSpinner
import javax.swing.JTabbedPane
import javax.swing.JTextArea
import javax.swing.SpinnerNumberModel
import javax.swing.event.ListSelectionEvent

class MemoryManagerDialog(
    private val project: Project,
    private val backendClient: BackendClient,
    private val projectRoot: String
) : DialogWrapper(project, true) {
    private val rulesModel = DefaultListModel<GenerationRuleDto>()
    private val rulesList = JBList(rulesModel)
    private val templatesModel = DefaultListModel<StepTemplateDto>()
    private val templatesList = JBList(templatesModel)
    private val rulesDetailsArea = createDetailsArea()
    private val templatesDetailsArea = createDetailsArea()
    private val rulesStatusArea = createDetailsArea()
    private val templatesStatusArea = createDetailsArea()

    init {
        title = "Project Memory"
        init()
        configureLists()
        loadAllAsync()
    }

    override fun createCenterPanel(): JComponent {
        val tabs = JTabbedPane()
        tabs.addTab("Rules", buildRulesPanel())
        tabs.addTab("Templates", buildTemplatesPanel())

        return JPanel(BorderLayout()).apply {
            preferredSize = Dimension(960, 620)
            border = JBUI.Borders.empty(8)
            add(tabs, BorderLayout.CENTER)
        }
    }

    private fun buildRulesPanel(): JPanel = JPanel(BorderLayout()).apply {
        add(buildContextHeader("Rule set for this project"), BorderLayout.NORTH)
        add(buildSplitView(rulesList, rulesDetailsArea), BorderLayout.CENTER)
        add(
            JPanel(BorderLayout()).apply {
                add(rulesStatusArea, BorderLayout.CENTER)
                add(
                    JPanel(GridLayout(1, 0, 8, 0)).apply {
                        border = JBUI.Borders.emptyTop(8)
                        add(JButton("Refresh").apply { addActionListener { loadRulesAsync() } })
                        add(JButton("Add").apply { addActionListener { addRule() } })
                        add(JButton("Edit").apply { addActionListener { editRule() } })
                        add(JButton("Delete").apply { addActionListener { deleteRule() } })
                    },
                    BorderLayout.SOUTH
                )
            },
            BorderLayout.SOUTH
        )
    }

    private fun buildTemplatesPanel(): JPanel = JPanel(BorderLayout()).apply {
        add(buildContextHeader("Step templates for this project"), BorderLayout.NORTH)
        add(buildSplitView(templatesList, templatesDetailsArea), BorderLayout.CENTER)
        add(
            JPanel(BorderLayout()).apply {
                add(templatesStatusArea, BorderLayout.CENTER)
                add(
                    JPanel(GridLayout(1, 0, 8, 0)).apply {
                        border = JBUI.Borders.emptyTop(8)
                        add(JButton("Refresh").apply { addActionListener { loadTemplatesAsync() } })
                        add(JButton("Add").apply { addActionListener { addTemplate() } })
                        add(JButton("Edit").apply { addActionListener { editTemplate() } })
                        add(JButton("Delete").apply { addActionListener { deleteTemplate() } })
                    },
                    BorderLayout.SOUTH
                )
            },
            BorderLayout.SOUTH
        )
    }

    private fun configureLists() {
        rulesList.emptyText.text = "No rules found for this project root."
        templatesList.emptyText.text = "No templates found for this project root."

        rulesList.cellRenderer = object : ColoredListCellRenderer<GenerationRuleDto>() {
            override fun customizeCellRenderer(
                list: JList<out GenerationRuleDto>,
                value: GenerationRuleDto?,
                index: Int,
                selected: Boolean,
                hasFocus: Boolean
            ) {
                if (value == null) return
                append(value.name, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                append("  p=${value.priority}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                append("  ${if (value.enabled) "enabled" else "disabled"}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                val regex = value.condition.textRegex?.takeIf { it.isNotBlank() } ?: "no regex"
                append("  match=$regex", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                val templateCount = value.actions.applyTemplates.size
                append("  templates=$templateCount", SimpleTextAttributes.GRAYED_ATTRIBUTES)
            }
        }
        templatesList.cellRenderer = object : ColoredListCellRenderer<StepTemplateDto>() {
            override fun customizeCellRenderer(
                list: JList<out StepTemplateDto>,
                value: StepTemplateDto?,
                index: Int,
                selected: Boolean,
                hasFocus: Boolean
            ) {
                if (value == null) return
                append(value.name, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                append("  p=${value.priority}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                append("  ${if (value.enabled) "enabled" else "disabled"}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                append("  steps=${value.steps.size}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                val regex = value.triggerRegex?.takeIf { it.isNotBlank() } ?: "manual or rule-linked"
                append("  trigger=$regex", SimpleTextAttributes.GRAYED_ATTRIBUTES)
            }
        }

        rulesList.addListSelectionListener { event: ListSelectionEvent ->
            if (!event.valueIsAdjusting) {
                rulesDetailsArea.text = rulesList.selectedValue?.let(::formatRuleDetails)
                    ?: "Select a rule to inspect its details."
            }
        }
        templatesList.addListSelectionListener { event: ListSelectionEvent ->
            if (!event.valueIsAdjusting) {
                templatesDetailsArea.text = templatesList.selectedValue?.let(::formatTemplateDetails)
                    ?: "Select a template to inspect its steps."
            }
        }

        rulesDetailsArea.text = "Select a rule to inspect its details."
        templatesDetailsArea.text = "Select a template to inspect its steps."
        rulesStatusArea.text = buildProjectContextText("Rules")
        templatesStatusArea.text = buildProjectContextText("Templates")
    }

    private fun loadAllAsync() {
        loadRulesAsync()
        loadTemplatesAsync()
    }

    private fun loadRulesAsync() {
        rulesStatusArea.text = "Loading rules for:\n$projectRoot"
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.listGenerationRules(projectRoot) }
                .onSuccess { response ->
                    ApplicationManager.getApplication().invokeLater {
                        rulesModel.clear()
                        response.items.forEach { rulesModel.addElement(it) }
                        rulesStatusArea.text = if (response.items.isEmpty()) {
                            buildProjectContextText("Rules") + "\n\nNo rules were saved for this project root."
                        } else {
                            buildProjectContextText("Rules") + "\n\nLoaded ${response.items.size} rule(s)."
                        }
                    }
                }
                .onFailure { ex ->
                    ApplicationManager.getApplication().invokeLater {
                        rulesStatusArea.text = buildProjectContextText("Rules") +
                            "\n\nFailed to load rules:\n${ex.message ?: "Unknown error"}"
                    }
                }
        }
    }

    private fun loadTemplatesAsync() {
        templatesStatusArea.text = "Loading templates for:\n$projectRoot"
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.listStepTemplates(projectRoot) }
                .onSuccess { response ->
                    ApplicationManager.getApplication().invokeLater {
                        templatesModel.clear()
                        response.items.forEach { templatesModel.addElement(it) }
                        templatesStatusArea.text = if (response.items.isEmpty()) {
                            buildProjectContextText("Templates") + "\n\nNo templates were saved for this project root."
                        } else {
                            buildProjectContextText("Templates") + "\n\nLoaded ${response.items.size} template(s)."
                        }
                    }
                }
                .onFailure { ex ->
                    ApplicationManager.getApplication().invokeLater {
                        templatesStatusArea.text = buildProjectContextText("Templates") +
                            "\n\nFailed to load templates:\n${ex.message ?: "Unknown error"}"
                    }
                }
        }
    }

    private fun addRule() {
        val formData = promptRuleForm() ?: return
        val request = GenerationRuleCreateRequestDto(
            projectRoot = projectRoot,
            name = formData.name,
            enabled = formData.enabled,
            priority = formData.priority,
            condition = GenerationRuleConditionDto(textRegex = formData.textRegex),
            actions = GenerationRuleActionsDto(
                qualityPolicy = formData.qualityPolicy,
                language = formData.language,
                targetPathTemplate = formData.targetPathTemplate,
                applyTemplates = formData.templateIds
            )
        )
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.createGenerationRule(request) }
                .onSuccess {
                    loadRulesAsync()
                    loadTemplatesAsync()
                }
                .onFailure { showError("Failed to create rule", it) }
        }
    }

    private fun editRule() {
        val selected = rulesList.selectedValue ?: return
        val formData = promptRuleForm(selected) ?: return
        val request = GenerationRulePatchRequestDto(
            projectRoot = projectRoot,
            name = formData.name,
            enabled = formData.enabled,
            priority = formData.priority,
            condition = GenerationRuleConditionDto(textRegex = formData.textRegex),
            actions = GenerationRuleActionsDto(
                qualityPolicy = formData.qualityPolicy,
                language = formData.language,
                targetPathTemplate = formData.targetPathTemplate,
                applyTemplates = formData.templateIds
            )
        )
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.updateGenerationRule(selected.id, request) }
                .onSuccess {
                    loadRulesAsync()
                    loadTemplatesAsync()
                }
                .onFailure { showError("Failed to update rule", it) }
        }
    }

    private fun deleteRule() {
        val selected = rulesList.selectedValue ?: return
        val confirmed = Messages.showYesNoDialog(
            project,
            "Delete rule '${selected.name}'?",
            "Delete Rule",
            Messages.getQuestionIcon()
        )
        if (confirmed != Messages.YES) return
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.deleteGenerationRule(selected.id, projectRoot) }
                .onSuccess { loadRulesAsync() }
                .onFailure { showError("Failed to delete rule", it) }
        }
    }

    private fun addTemplate() {
        val formData = promptTemplateForm() ?: return
        val request = StepTemplateCreateRequestDto(
            projectRoot = projectRoot,
            name = formData.name,
            enabled = formData.enabled,
            priority = formData.priority,
            triggerRegex = formData.triggerRegex,
            steps = formData.steps
        )
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.createStepTemplate(request) }
                .onSuccess { loadTemplatesAsync() }
                .onFailure { showError("Failed to create template", it) }
        }
    }

    private fun editTemplate() {
        val selected = templatesList.selectedValue ?: return
        val formData = promptTemplateForm(selected) ?: return
        val request = StepTemplatePatchRequestDto(
            projectRoot = projectRoot,
            name = formData.name,
            enabled = formData.enabled,
            priority = formData.priority,
            triggerRegex = formData.triggerRegex,
            steps = formData.steps
        )
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.updateStepTemplate(selected.id, request) }
                .onSuccess { loadTemplatesAsync() }
                .onFailure { showError("Failed to update template", it) }
        }
    }

    private fun deleteTemplate() {
        val selected = templatesList.selectedValue ?: return
        val linkedRuleNames = rulesModel.elements().toList()
            .filter { it.actions.applyTemplates.contains(selected.id) }
            .map { it.name }
        val warning = if (linkedRuleNames.isEmpty()) {
            "Delete template '${selected.name}'?"
        } else {
            "Delete template '${selected.name}'?\n\nIt is referenced by rule(s): ${linkedRuleNames.joinToString(", ")}"
        }
        val confirmed = Messages.showYesNoDialog(
            project,
            warning,
            "Delete Template",
            Messages.getWarningIcon()
        )
        if (confirmed != Messages.YES) return
        ApplicationManager.getApplication().executeOnPooledThread {
            runCatching { backendClient.deleteStepTemplate(selected.id, projectRoot) }
                .onSuccess {
                    loadTemplatesAsync()
                    loadRulesAsync()
                }
                .onFailure { showError("Failed to delete template", it) }
        }
    }

    private fun promptTemplateForm(existing: StepTemplateDto? = null): TemplateFormData? {
        val nameField = JBTextField(existing?.name.orEmpty())
        val enabledCheckbox = JCheckBox("Enabled", existing?.enabled ?: true)
        val prioritySpinner = JSpinner(SpinnerNumberModel(existing?.priority ?: 100, 0, 10000, 1))
        val triggerField = JBTextField(existing?.triggerRegex.orEmpty())
        val stepsArea = JBTextArea(existing?.steps?.joinToString("\n").orEmpty()).apply {
            lineWrap = true
            wrapStyleWord = true
            rows = 8
        }

        val form = panel {
            row("Name:") { cell(nameField).resizableColumn() }
            row { cell(enabledCheckbox) }
            row("Priority:") { cell(prioritySpinner) }
            row("Trigger regex:") { cell(triggerField).resizableColumn() }
            row("Steps:") { cell(JBScrollPane(stepsArea)).resizableColumn() }
        }

        val result = JOptionPane.showConfirmDialog(
            null,
            form,
            if (existing == null) "Add Template" else "Edit Template",
            JOptionPane.OK_CANCEL_OPTION,
            JOptionPane.PLAIN_MESSAGE
        )
        if (result != JOptionPane.OK_OPTION) return null

        val name = nameField.text.trim()
        val steps = stepsArea.text.lines().map { it.trim() }.filter { it.isNotBlank() }
        if (name.isBlank()) {
            Messages.showWarningDialog(project, "Template name must not be empty.", "Template")
            return null
        }
        if (steps.isEmpty()) {
            Messages.showWarningDialog(project, "Template must contain at least one step.", "Template")
            return null
        }
        return TemplateFormData(
            name = name,
            enabled = enabledCheckbox.isSelected,
            priority = (prioritySpinner.value as Number).toInt(),
            triggerRegex = triggerField.text.trim().ifBlank { null },
            steps = steps
        )
    }

    private fun promptRuleForm(existing: GenerationRuleDto? = null): RuleFormData? {
        val nameField = JBTextField(existing?.name.orEmpty())
        val enabledCheckbox = JCheckBox("Enabled", existing?.enabled ?: true)
        val prioritySpinner = JSpinner(SpinnerNumberModel(existing?.priority ?: 100, 0, 10000, 1))
        val textRegexField = JBTextField(existing?.condition?.textRegex.orEmpty())
        val targetPathField = JBTextField(existing?.actions?.targetPathTemplate.orEmpty())
        val qualityCombo = JComboBox(arrayOf("", "strict", "balanced", "lenient")).apply {
            selectedItem = existing?.actions?.qualityPolicy.orEmpty()
        }
        val languageCombo = JComboBox(arrayOf("", "ru", "en")).apply {
            selectedItem = existing?.actions?.language.orEmpty()
        }
        val templateList = JBList(templatesModel).apply {
            selectionMode = javax.swing.ListSelectionModel.MULTIPLE_INTERVAL_SELECTION
        }
        val selectedTemplateIds = existing?.actions?.applyTemplates.orEmpty().toSet()
        val selectedIndices = templatesModel.elements().toList().mapIndexedNotNull { index, template ->
            index.takeIf { template.id in selectedTemplateIds }
        }.toIntArray()
        if (selectedIndices.isNotEmpty()) {
            templateList.selectedIndices = selectedIndices
        }

        val form = panel {
            row("Name:") { cell(nameField).resizableColumn() }
            row { cell(enabledCheckbox) }
            row("Priority:") { cell(prioritySpinner) }
            row("Text regex:") { cell(textRegexField).resizableColumn() }
            row("Quality policy:") { cell(qualityCombo) }
            row("Language:") { cell(languageCombo) }
            row("Target path template:") { cell(targetPathField).resizableColumn() }
            row("Templates:") { cell(JBScrollPane(templateList).apply { preferredSize = Dimension(320, 140) }).resizableColumn() }
        }

        val result = JOptionPane.showConfirmDialog(
            null,
            form,
            if (existing == null) "Add Rule" else "Edit Rule",
            JOptionPane.OK_CANCEL_OPTION,
            JOptionPane.PLAIN_MESSAGE
        )
        if (result != JOptionPane.OK_OPTION) return null

        val templateIds = templateList.selectedValuesList.map { it.id }
        val name = nameField.text.trim()
        val textRegex = textRegexField.text.trim().ifBlank { null }
        val quality = qualityCombo.selectedItem?.toString()?.trim().orEmpty().ifBlank { null }
        val language = languageCombo.selectedItem?.toString()?.trim().orEmpty().ifBlank { null }
        val targetPathTemplate = targetPathField.text.trim().ifBlank { null }
        if (name.isBlank()) {
            Messages.showWarningDialog(project, "Rule name must not be empty.", "Rule")
            return null
        }
        if (textRegex == null && quality == null && language == null && targetPathTemplate == null && templateIds.isEmpty()) {
            Messages.showWarningDialog(project, "Rule must define at least one condition or action.", "Rule")
            return null
        }
        return RuleFormData(
            name = name,
            enabled = enabledCheckbox.isSelected,
            priority = (prioritySpinner.value as Number).toInt(),
            textRegex = textRegex,
            qualityPolicy = quality,
            language = language,
            targetPathTemplate = targetPathTemplate,
            templateIds = templateIds
        )
    }

    private fun buildSplitView(list: JList<*>, detailsArea: JBTextArea): JComponent {
        return panel {
            row {
                cell(JBScrollPane(list).apply { preferredSize = Dimension(420, 360) })
                cell(JBScrollPane(detailsArea).apply { preferredSize = Dimension(420, 360) })
            }
        }
    }

    private fun buildContextHeader(title: String): JComponent {
        return JTextArea().apply {
            text = "$title\nProject root: $projectRoot"
            isEditable = false
            border = JBUI.Borders.emptyBottom(8)
            background = JBColor.PanelBackground
            foreground = JBColor.foreground()
            lineWrap = true
            wrapStyleWord = true
        }
    }

    private fun createDetailsArea(): JBTextArea = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(8)
        background = JBColor.PanelBackground
        foreground = JBColor.foreground()
    }

    private fun buildProjectContextText(kind: String): String =
        "$kind for project root:\n$projectRoot"

    private fun showError(title: String, throwable: Throwable) {
        ApplicationManager.getApplication().invokeLater {
            Messages.showErrorDialog(project, throwable.message ?: title, title)
        }
    }

    private fun formatRuleDetails(rule: GenerationRuleDto): String {
        val condition = rule.condition
        val actions = rule.actions
        return buildString {
            appendLine("Rule: ${rule.name}")
            appendLine("Id: ${rule.id}")
            appendLine("Enabled: ${rule.enabled}")
            appendLine("Priority: ${rule.priority}")
            appendLine("Source: ${rule.source}")
            appendLine()
            appendLine("Conditions")
            appendLine("- textRegex: ${condition.textRegex ?: "<none>"}")
            appendLine("- jiraKeyPattern: ${condition.jiraKeyPattern ?: "<none>"}")
            appendLine("- languageIn: ${condition.languageIn.joinToString().ifBlank { "<none>" }}")
            appendLine("- qualityPolicyIn: ${condition.qualityPolicyIn.joinToString().ifBlank { "<none>" }}")
            appendLine()
            appendLine("Actions")
            appendLine("- qualityPolicy: ${actions.qualityPolicy ?: "<none>"}")
            appendLine("- language: ${actions.language ?: "<none>"}")
            appendLine("- targetPathTemplate: ${actions.targetPathTemplate ?: "<none>"}")
            appendLine("- applyTemplates: ${resolveTemplateNames(actions.applyTemplates)}")
        }
    }

    private fun formatTemplateDetails(template: StepTemplateDto): String {
        return buildString {
            appendLine("Template: ${template.name}")
            appendLine("Id: ${template.id}")
            appendLine("Enabled: ${template.enabled}")
            appendLine("Priority: ${template.priority}")
            appendLine("Source: ${template.source}")
            appendLine("Trigger regex: ${template.triggerRegex ?: "<none>"}")
            appendLine()
            appendLine("Steps")
            template.steps.forEachIndexed { index, step ->
                appendLine("${index + 1}. $step")
            }
        }
    }

    private fun resolveTemplateNames(templateIds: List<String>): String {
        if (templateIds.isEmpty()) return "<none>"
        val templatesById = templatesModel.elements().toList().associateBy { it.id }
        return templateIds.joinToString { templateId ->
            templatesById[templateId]?.name ?: templateId
        }
    }
}

private data class TemplateFormData(
    val name: String,
    val enabled: Boolean,
    val priority: Int,
    val triggerRegex: String?,
    val steps: List<String>
)

private data class RuleFormData(
    val name: String,
    val enabled: Boolean,
    val priority: Int,
    val textRegex: String?,
    val qualityPolicy: String?,
    val language: String?,
    val targetPathTemplate: String?,
    val templateIds: List<String>
)

private fun <T> DefaultListModel<T>.elements(): List<T> =
    (0 until size()).map(::getElementAt)

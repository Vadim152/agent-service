package ru.sber.aitestplugin.config

import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBCheckBox
import com.intellij.util.ui.JBUI
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel

/**
 * Панель настроек плагина (Settings/Preferences → Tools → "AI Test Agent").
 */
class AiTestPluginSettingsConfigurable : Configurable {
    private val settingsService = AiTestPluginSettingsService.getInstance()

    private val scanStepsCheckbox = JBCheckBox("Сканировать шаги")
    private val foundStepsCheckbox = JBCheckBox("Найденные шаги")
    private val unmappedStepsCheckbox = JBCheckBox("Неотображенные шаги")

    private val rootPanel: JPanel = JPanel(GridBagLayout()).apply {
        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            weightx = 1.0
            fill = GridBagConstraints.HORIZONTAL
            anchor = GridBagConstraints.NORTHWEST
            insets = JBUI.insetsBottom(12)
        }

        add(sectionLabel("Инструменты"), gbc)
        gbc.gridy++
        add(scanStepsCheckbox, gbc)
        gbc.gridy++
        add(foundStepsCheckbox, gbc)
        gbc.gridy++
        add(unmappedStepsCheckbox, gbc)
    }

    override fun getDisplayName(): String = "AI Test Agent"

    override fun createComponent(): JComponent = rootPanel

    override fun isModified(): Boolean {
        val saved = settingsService.settings
        return scanStepsCheckbox.isSelected != saved.showScanSteps ||
            foundStepsCheckbox.isSelected != saved.showFoundSteps ||
            unmappedStepsCheckbox.isSelected != saved.showUnmappedSteps
    }

    override fun apply() {
        settingsService.settings.apply {
            this.showScanSteps = scanStepsCheckbox.isSelected
            this.showFoundSteps = foundStepsCheckbox.isSelected
            this.showUnmappedSteps = unmappedStepsCheckbox.isSelected
        }
    }

    override fun reset() {
        val saved = settingsService.settings
        scanStepsCheckbox.isSelected = saved.showScanSteps
        foundStepsCheckbox.isSelected = saved.showFoundSteps
        unmappedStepsCheckbox.isSelected = saved.showUnmappedSteps
    }

    private fun sectionLabel(text: String): JLabel = JLabel(text).apply {
        border = JBUI.Borders.empty(4, 0, 6, 0)
    }
}

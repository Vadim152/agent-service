package ru.sber.aitestplugin.config

import com.intellij.openapi.options.ConfigurationException
import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBCheckBox
import com.intellij.util.ui.JBUI
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import javax.swing.JComboBox
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JSpinner
import javax.swing.JTextField
import javax.swing.SpinnerNumberModel

/**
 * Панель настроек плагина (Settings/Preferences → "AI Test Agent").
 * Позволяет редактировать URL backend, таймаут и настройки сценариев/сканирования.
 */
class AiTestPluginSettingsConfigurable : Configurable {
    private val settingsService = AiTestPluginSettingsService.getInstance()

    private val backendUrlField = JTextField()
    private val timeoutField = JTextField()

    private val scanProjectRootField = JTextField()
    private val scanDepthSpinner = JSpinner(SpinnerNumberModel(AiTestPluginSettings.DEFAULT_SCAN_DEPTH, 1, 10_000, 1))
    private val scanPatternField = JTextField()
    private val scanLanguageCombo = JComboBox(arrayOf("auto", "ru", "en"))

    private val generateTargetPathField = JTextField()
    private val generateCreateFileCheckbox = JBCheckBox("Создавать файл при отсутствии")
    private val generateOverwriteCheckbox = JBCheckBox("Перезаписывать существующий файл")
    private val generateLanguageField = JTextField()

    private val applyTargetPathField = JTextField()
    private val applyCreateFileCheckbox = JBCheckBox("Создавать файл при отсутствии")
    private val applyOverwriteCheckbox = JBCheckBox("Перезаписывать существующий файл")

    private val rootPanel: JPanel = JPanel(GridBagLayout()).apply {
        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            weightx = 1.0
            fill = GridBagConstraints.HORIZONTAL
            anchor = GridBagConstraints.NORTHWEST
            insets = JBUI.insetsBottom(12)
        }

        add(sectionLabel("Подключение к бэкенду"), gbc)
        gbc.gridy++
        add(labeledRow("URL бэкенда", backendUrlField), gbc)
        gbc.gridy++
        add(labeledRow("Таймаут (мс)", timeoutField), gbc)

        gbc.gridy++
        add(sectionLabel("Сканирование шагов"), gbc)
        gbc.gridy++
        add(labeledRow("Корень проекта по умолчанию", scanProjectRootField), gbc)
        gbc.gridy++
        add(labeledRow("Глубина поиска", scanDepthSpinner), gbc)
        gbc.gridy++
        add(labeledRow("Паттерн файлов", scanPatternField), gbc)
        gbc.gridy++
        add(labeledRow("Язык интерфейса", scanLanguageCombo), gbc)

        gbc.gridy++
        add(sectionLabel("Генерация feature"), gbc)
        gbc.gridy++
        add(labeledRow("Целевой путь по умолчанию", generateTargetPathField), gbc)
        gbc.gridy++
        add(generateCreateFileCheckbox, gbc)
        gbc.gridy++
        add(generateOverwriteCheckbox, gbc)
        gbc.gridy++
        add(labeledRow("Язык генерации", generateLanguageField), gbc)

        gbc.gridy++
        add(sectionLabel("Применение feature"), gbc)
        gbc.gridy++
        add(labeledRow("Целевой путь по умолчанию", applyTargetPathField), gbc)
        gbc.gridy++
        add(applyCreateFileCheckbox, gbc)
        gbc.gridy++
        add(applyOverwriteCheckbox, gbc)
    }

    override fun getDisplayName(): String = "AI Test Agent"

    override fun createComponent(): JComponent = rootPanel

    override fun isModified(): Boolean {
        val saved = settingsService.settings
        return backendUrlField.text.trim() != saved.backendUrl ||
            timeoutField.text.trim() != saved.requestTimeoutMs.toString() ||
            scanProjectRootField.text.trim() != (saved.scanProjectRoot ?: "") ||
            (scanDepthSpinner.value as? Int ?: saved.scanSearchDepth) != saved.scanSearchDepth ||
            scanPatternField.text.trim() != saved.scanFilePattern ||
            scanLanguageCombo.selectedItem != saved.scanLanguage ||
            generateTargetPathField.text.trim() != (saved.generateFeatureTargetPath ?: "") ||
            generateCreateFileCheckbox.isSelected != saved.generateFeatureCreateFile ||
            generateOverwriteCheckbox.isSelected != saved.generateFeatureOverwriteExisting ||
            generateLanguageField.text.trim() != (saved.generateFeatureLanguage ?: "") ||
            applyTargetPathField.text.trim() != (saved.applyFeatureTargetPath ?: "") ||
            applyCreateFileCheckbox.isSelected != saved.applyFeatureCreateFile ||
            applyOverwriteCheckbox.isSelected != saved.applyFeatureOverwriteExisting
    }

    override fun apply() {
        val backendUrl = backendUrlField.text.trim()
        val timeout = timeoutField.text.trim().toIntOrNull() ?: throw ConfigurationException("Таймаут должен быть целым числом")
        validateBackendUrl(backendUrl)
        if (timeout <= 0) throw ConfigurationException("Таймаут должен быть положительным")

        val scanDepth = (scanDepthSpinner.value as? Int) ?: throw ConfigurationException("Глубина поиска должна быть числом")
        if (scanDepth <= 0) throw ConfigurationException("Глубина поиска должна быть больше 0")

        settingsService.settings.apply {
            this.backendUrl = backendUrl
            this.requestTimeoutMs = timeout
            this.scanProjectRoot = scanProjectRootField.text.trim().ifEmpty { null }
            this.scanSearchDepth = scanDepth
            this.scanFilePattern = scanPatternField.text.trim().ifEmpty { AiTestPluginSettings.DEFAULT_SCAN_PATTERN }
            this.scanLanguage = (scanLanguageCombo.selectedItem as? String)?.ifBlank { AiTestPluginSettings.DEFAULT_LANGUAGE }
                ?: AiTestPluginSettings.DEFAULT_LANGUAGE

            this.generateFeatureTargetPath = generateTargetPathField.text.trim().ifEmpty { null }
            this.generateFeatureCreateFile = generateCreateFileCheckbox.isSelected
            this.generateFeatureOverwriteExisting = generateOverwriteCheckbox.isSelected
            this.generateFeatureLanguage = generateLanguageField.text.trim().ifEmpty { null }

            this.applyFeatureTargetPath = applyTargetPathField.text.trim().ifEmpty { null }
            this.applyFeatureCreateFile = applyCreateFileCheckbox.isSelected
            this.applyFeatureOverwriteExisting = applyOverwriteCheckbox.isSelected
        }
    }

    override fun reset() {
        val saved = settingsService.settings
        backendUrlField.text = saved.backendUrl
        timeoutField.text = saved.requestTimeoutMs.toString()

        scanProjectRootField.text = saved.scanProjectRoot ?: ""
        scanDepthSpinner.value = saved.scanSearchDepth
        scanPatternField.text = saved.scanFilePattern
        val languageToSelect = (0 until scanLanguageCombo.itemCount)
            .map { scanLanguageCombo.getItemAt(it) }
            .firstOrNull { it == saved.scanLanguage }
            ?: AiTestPluginSettings.DEFAULT_LANGUAGE
        scanLanguageCombo.selectedItem = languageToSelect

        generateTargetPathField.text = saved.generateFeatureTargetPath ?: ""
        generateCreateFileCheckbox.isSelected = saved.generateFeatureCreateFile
        generateOverwriteCheckbox.isSelected = saved.generateFeatureOverwriteExisting
        generateLanguageField.text = saved.generateFeatureLanguage ?: ""

        applyTargetPathField.text = saved.applyFeatureTargetPath ?: ""
        applyCreateFileCheckbox.isSelected = saved.applyFeatureCreateFile
        applyOverwriteCheckbox.isSelected = saved.applyFeatureOverwriteExisting
    }

    private fun validateBackendUrl(url: String) {
        if (url.isBlank()) {
            throw ConfigurationException("Backend URL не может быть пустым")
        }

        val parsedUrl = try {
            java.net.URL(url)
        } catch (ex: java.net.MalformedURLException) {
            throw ConfigurationException("Некорректный backend URL: ${ex.message}")
        }

        val protocol = parsedUrl.protocol?.lowercase()
        if (protocol != "http" && protocol != "https") {
            throw ConfigurationException("Backend URL должен начинаться с http:// или https://")
        }
    }

    private fun sectionLabel(text: String): JLabel = JLabel(text).apply {
        border = JBUI.Borders.empty(4, 0, 6, 0)
    }

    private fun labeledRow(label: String, component: JComponent): JPanel = JPanel(GridBagLayout()).apply {
        val gbc = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            weightx = 0.0
            anchor = GridBagConstraints.WEST
            insets = JBUI.insetsRight(8)
        }
        add(JLabel(label), gbc)
        gbc.gridx = 1
        gbc.weightx = 1.0
        gbc.fill = GridBagConstraints.HORIZONTAL
        add(component, gbc)
        border = JBUI.Borders.emptyBottom(6)
    }
}

package ru.sber.aitestplugin.config

import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JTextField

/**
 * Панель настроек плагина (Settings/Preferences → "AI Test Agent").
 * Позволит редактировать URL backend и таймауты.
 */
class AiTestPluginSettingsConfigurable : com.intellij.openapi.options.Configurable {
    private val backendUrlField = JTextField(AiTestPluginSettings.DEFAULT_BACKEND_URL)
    private val rootPanel: JPanel = JPanel().apply {
        add(backendUrlField)
    }

    override fun getDisplayName(): String = "AI Test Agent"

    override fun createComponent(): JComponent = rootPanel

    override fun isModified(): Boolean {
        // TODO: сравнить текущее значение с сохранённым состоянием
        return true
    }

    override fun apply() {
        // TODO: сохранить настройки через PersistentStateComponent
    }

    override fun reset() {
        // TODO: сбрасывать поля к сохранённому состоянию
    }
}
